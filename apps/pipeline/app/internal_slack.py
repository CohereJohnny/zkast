"""Internal HTTP API for Slack connect, channel registration, threads, and import.

Connect → list channels → register channel → list/cache threads → import a
channel's conversation units (threads + session windows) into the shared
ingestion spine (parse → notes → graph). See specs/openspecs/slack-source.md.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.job_redis import job_hset
from app.north_repo import list_north_agents, upsert_north_agent
from app.secrets import decrypt, encrypt
from app.slack_client import (
    DEFAULT_SLACK_BOT_SCOPES,
    SlackApiError,
    SlackAuthError,
    SlackClient,
    build_authorize_url,
    build_user_name_map,
    exchange_oauth_code,
)
from app.slack_repo import (
    fetch_slack_connection,
    fetch_slack_oauth_secret_row,
    delete_slack_connection,
    delete_slack_oauth_token,
    list_slack_conversation_cache,
    store_slack_oauth_token,
    upsert_slack_connection,
    upsert_slack_conversation_cache,
)
from app.slack_transcript import DEFAULT_SESSION_GAP_SECONDS

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["internal-slack"])

SLACK_PROVIDER = "slack"

# In-process TTL cache for the (slow, rate-limited) Slack channel listing.
# Keyed by workspace id -> (fetched_at_epoch, raw_channels). Registered state
# is merged fresh from Postgres on every request, so only the Slack API result
# is cached.
_CHANNELS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CHANNELS_CACHE_TTL_S = 300.0


def _slack_source_or_404(settings: Settings, ws: str, source_id: str) -> dict[str, Any]:
    sources = {
        a["id"]: a
        for a in list_north_agents(settings.database_url, workspace_id=ws)
        if a.get("provider") == SLACK_PROVIDER
    }
    source = sources.get(source_id)
    if not source:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "source_not_found", "message": "Slack channel source not found."}},
        )
    return source


def _require_slack_app(settings: Settings) -> tuple[str, str, str]:
    cid = (settings.slack_client_id or "").strip()
    secret = (settings.slack_client_secret or "").strip()
    redirect = (settings.slack_redirect_uri or "").strip()
    if not cid or not secret or not redirect:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "slack_app_not_configured",
                    "message": (
                        "Slack OAuth app is not configured. Set SLACK_CLIENT_ID, "
                        "SLACK_CLIENT_SECRET, and SLACK_REDIRECT_URI on the pipeline."
                    ),
                }
            },
        )
    return cid, secret, redirect


def _resolve_slack_token(settings: Settings, workspace_id: str) -> str:
    enc = fetch_slack_oauth_secret_row(settings.database_url, workspace_id)
    if not enc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "slack_not_connected",
                    "message": "Connect Slack first (no OAuth token stored for this workspace).",
                }
            },
        )
    return decrypt(settings.master_encryption_key_bytes, enc).decode("utf-8")


def _slack_client(settings: Settings, workspace_id: str) -> SlackClient:
    return SlackClient(bot_token=_resolve_slack_token(settings, workspace_id))


# --------------------------------------------------------------------------- #
# Connection status + OAuth
# --------------------------------------------------------------------------- #
@router.get("/internal/v1/workspaces/{workspace_id}/slack/connection")
async def get_slack_connection(workspace_id: uuid.UUID, request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    conn = fetch_slack_connection(settings.database_url, workspace_id=str(workspace_id))
    has_token = bool(fetch_slack_oauth_secret_row(settings.database_url, str(workspace_id)))
    return JSONResponse(
        content={
            "connected": bool(conn and has_token),
            "connection": conn,  # team id/name + scopes only; never the token
        }
    )


@router.post("/internal/v1/workspaces/{workspace_id}/slack/oauth/start")
async def post_slack_oauth_start(workspace_id: uuid.UUID, request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    client_id, _secret, redirect_uri = _require_slack_app(settings)
    # State binds the callback to this workspace and a nonce; caller persists
    # and verifies it on return.
    state = f"{workspace_id}:{uuid.uuid4().hex}"
    url = build_authorize_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        scopes=DEFAULT_SLACK_BOT_SCOPES,
    )
    return JSONResponse(content={"authorize_url": url, "state": state})


@router.post("/internal/v1/workspaces/{workspace_id}/slack/oauth/callback")
async def post_slack_oauth_callback(
    workspace_id: uuid.UUID, request: Request
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    client_id, client_secret, redirect_uri = _require_slack_app(settings)
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    code = str(body.get("code") or "").strip()
    state = str(body.get("state") or "").strip()
    if not code:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "missing_code", "message": "OAuth code is required."}},
        )
    if state and not state.startswith(f"{workspace_id}:"):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "state_mismatch", "message": "OAuth state does not match workspace."}},
        )
    try:
        payload = await exchange_oauth_code(
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=str(body.get("redirect_uri") or redirect_uri),
        )
    except SlackAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "slack_oauth_failed", "message": str(exc)}},
        ) from exc

    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "slack_no_token", "message": "Slack returned no access token."}},
        )
    team = payload.get("team") or {}
    team_id = str(team.get("id") or payload.get("team_id") or "").strip()
    team_name = str(team.get("name") or "").strip() or None
    scopes = [s for s in str(payload.get("scope") or "").split(",") if s]

    enc = encrypt(settings.master_encryption_key_bytes, access_token.encode("utf-8"))
    store_slack_oauth_token(
        settings.database_url,
        workspace_id=str(workspace_id),
        encrypted_secret=enc,
        metadata={"team_id": team_id, "scopes": scopes},
    )
    conn = upsert_slack_connection(
        settings.database_url,
        workspace_id=str(workspace_id),
        slack_team_id=team_id,
        slack_team_name=team_name,
        authed_scopes=scopes,
    )
    return JSONResponse(content={"connected": True, "connection": conn})


@router.post("/internal/v1/workspaces/{workspace_id}/slack/connect-token")
async def post_slack_connect_token(
    workspace_id: uuid.UUID, request: Request
) -> JSONResponse:
    """Connect Slack with a bot token (``xoxb-…``) directly.

    Local/self-hosted convenience that skips the OAuth redirect (which requires
    HTTPS). Verifies the token via ``auth.test``, stores it encrypted, and
    records the connection. Mirrors the North bearer-token path.
    """
    settings: Settings = request.app.state.settings
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    token = str(body.get("bot_token") or "").strip()
    if not token:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "missing_bot_token", "message": "bot_token is required."}},
        )

    try:
        info = await SlackClient(bot_token=token).auth_test()
    except SlackAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "slack_auth", "message": str(exc)}},
        ) from exc
    except SlackApiError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "slack_api", "message": str(exc)}},
        ) from exc

    team_id = str(info.get("team_id") or "").strip()
    team_name = str(info.get("team") or "").strip() or None

    enc = encrypt(settings.master_encryption_key_bytes, token.encode("utf-8"))
    store_slack_oauth_token(
        settings.database_url,
        workspace_id=str(workspace_id),
        encrypted_secret=enc,
        label=f"Slack bot token ({team_name or team_id or 'workspace'})",
        metadata={"team_id": team_id, "auth": "bot_token"},
    )
    conn = upsert_slack_connection(
        settings.database_url,
        workspace_id=str(workspace_id),
        slack_team_id=team_id,
        slack_team_name=team_name,
        authed_scopes=[],
    )
    return JSONResponse(content={"connected": True, "connection": conn})


@router.delete("/internal/v1/workspaces/{workspace_id}/slack/connection")
async def delete_slack_connection_route(
    workspace_id: uuid.UUID, request: Request
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    delete_slack_oauth_token(settings.database_url, str(workspace_id))
    delete_slack_connection(settings.database_url, workspace_id=str(workspace_id))
    return JSONResponse(content={"connected": False})


# --------------------------------------------------------------------------- #
# Channels (memory sources, provider='slack')
# --------------------------------------------------------------------------- #
def _serialize_slack_source(src: dict[str, Any]) -> dict[str, Any]:
    sync = src.get("provider_metadata") if isinstance(src.get("provider_metadata"), dict) else None
    return {
        "source_id": src.get("id"),
        "channel_id": src.get("external_agent_id"),
        "name": src.get("display_name"),
        "sync": sync or None,
    }


@router.get("/internal/v1/workspaces/{workspace_id}/slack/sources")
async def get_slack_sources(workspace_id: uuid.UUID, request: Request) -> JSONResponse:
    """Registered Slack channels for this workspace (fast — Postgres only).

    Lets the UI show importable channels + sync coverage without the slow,
    rate-limited full channel listing.
    """
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    sources = [
        _serialize_slack_source(a)
        for a in list_north_agents(settings.database_url, workspace_id=ws)
        if a.get("provider") == SLACK_PROVIDER
    ]
    sources.sort(key=lambda s: str(s.get("name") or ""))
    return JSONResponse(content={"items": sources})


@router.get("/internal/v1/workspaces/{workspace_id}/slack/channels")
async def get_slack_channels(
    workspace_id: uuid.UUID,
    request: Request,
    refresh: bool = Query(default=False),
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)

    cached = _CHANNELS_CACHE.get(ws)
    fresh = cached is not None and (time.time() - cached[0]) < _CHANNELS_CACHE_TTL_S
    if fresh and not refresh:
        channels = cached[1]
        from_cache = True
    else:
        client = _slack_client(settings, ws)
        try:
            channels = await client.list_channels()
        except SlackAuthError as exc:
            raise HTTPException(
                status_code=401,
                detail={"error": {"code": "slack_auth", "message": str(exc)}},
            ) from exc
        except SlackApiError as exc:
            raise HTTPException(
                status_code=502,
                detail={"error": {"code": "slack_api", "message": str(exc)}},
            ) from exc
        _CHANNELS_CACHE[ws] = (time.time(), channels)
        from_cache = False

    registered: dict[str, dict[str, Any]] = {
        a["external_agent_id"]: a
        for a in list_north_agents(settings.database_url, workspace_id=ws)
        if a.get("provider") == SLACK_PROVIDER and a.get("external_agent_id")
    }
    items = []
    for c in channels:
        cid = c.get("id")
        if not cid:
            continue
        src = registered.get(cid)
        sync = src.get("provider_metadata") if src and isinstance(src.get("provider_metadata"), dict) else None
        items.append(
            {
                "channel_id": cid,
                "name": c.get("name"),
                "is_private": bool(c.get("is_private")),
                "is_member": bool(c.get("is_member")),
                "num_members": c.get("num_members"),
                "topic": (c.get("topic") or {}).get("value") if isinstance(c.get("topic"), dict) else None,
                "registered": src is not None,
                "source_id": src.get("id") if src else None,
                "sync": sync or None,
            }
        )
    return JSONResponse(content={"items": items, "from_cache": from_cache})


@router.post("/internal/v1/workspaces/{workspace_id}/slack/channels/register")
async def post_register_channel(
    workspace_id: uuid.UUID, request: Request
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    channel_id = str(body.get("channel_id") or "").strip()
    if not channel_id:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "missing_channel_id", "message": "channel_id is required."}},
        )
    channel_name = str(body.get("channel_name") or channel_id).strip()
    import_settings = body.get("import_settings") if isinstance(body.get("import_settings"), dict) else {}
    source = upsert_north_agent(
        settings.database_url,
        workspace_id=str(workspace_id),
        external_agent_id=channel_id,
        display_name=channel_name,
        provider=SLACK_PROVIDER,
        import_settings=import_settings,
    )
    return JSONResponse(content={"source": source})


# --------------------------------------------------------------------------- #
# Threads (root messages + cached replies)
# --------------------------------------------------------------------------- #
@router.get("/internal/v1/workspaces/{workspace_id}/slack/channels/{source_id}/threads")
async def get_channel_threads(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    request: Request,
    refresh: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    sources = {
        a["id"]: a
        for a in list_north_agents(settings.database_url, workspace_id=ws)
        if a.get("provider") == SLACK_PROVIDER
    }
    source = sources.get(str(source_id))
    if not source:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "source_not_found", "message": "Slack channel source not found."}},
        )

    if not refresh:
        cached = list_slack_conversation_cache(
            settings.database_url, workspace_id=ws, source_id=str(source_id), limit=limit
        )
        if cached:
            return JSONResponse(content={"items": cached, "from_cache": True})

    channel_id = source["external_agent_id"]
    client = _slack_client(settings, ws)
    try:
        roots = await client.channel_history(channel_id=channel_id, limit=min(limit, 200))
    except SlackAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "slack_auth", "message": str(exc)}},
        ) from exc
    except SlackApiError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "slack_api", "message": str(exc)}},
        ) from exc

    # Best-effort author-name resolution (requires users:read). Never fatal.
    user_names: dict[str, str] = {}
    try:
        user_names = build_user_name_map(await client.list_users())
    except (SlackAuthError, SlackApiError) as exc:
        logger.info("slack_user_resolution_skipped", error=str(exc))

    items: list[dict[str, Any]] = []
    for msg in roots[:limit]:
        ts = str(msg.get("thread_ts") or msg.get("ts") or "").strip()
        if not ts:
            continue
        external_conversation_id = f"{channel_id}:{ts}"
        author = str(msg.get("user") or "").strip()
        upsert_slack_conversation_cache(
            settings.database_url,
            workspace_id=ws,
            source_id=str(source_id),
            external_conversation_id=external_conversation_id,
            payload={"root": msg, "channel_id": channel_id, "thread_ts": ts},
        )
        items.append(
            {
                "external_conversation_id": external_conversation_id,
                "thread_ts": ts,
                "reply_count": msg.get("reply_count", 0),
                "text_preview": str(msg.get("text") or "")[:280],
                "user": author or None,
                "user_name": user_names.get(author) if author else None,
            }
        )
    return JSONResponse(content={"items": items, "from_cache": False})


# --------------------------------------------------------------------------- #
# Import — segment channel into documents and enqueue parse → notes → graph
# --------------------------------------------------------------------------- #
@router.post("/internal/v1/workspaces/{workspace_id}/slack/channels/{source_id}/import")
async def post_import_threads(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    """Kick off a channel import in the background and return a job to watch.

    Busy channels have thousands of threads; fetching replies synchronously
    would block for minutes. We enqueue a worker job that fetches + segments +
    creates ``slack_conversation`` documents (then the normal parse → notes →
    graph pipeline) and streams progress to the job log.
    """
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    sid = str(source_id)
    source = _slack_source_or_404(settings, ws, sid)

    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    history_limit = max(1, min(int(body.get("history_limit") or 1000), 1000))
    session_gap = int(body.get("session_gap_seconds") or DEFAULT_SESSION_GAP_SECONDS)
    segmentation_mode = str(body.get("segmentation_mode") or "turn")
    range_key = str(body.get("range") or "last_90_days")
    cutoff_date = body.get("cutoff_date")
    channel_id = source["external_agent_id"]
    channel_name = source.get("display_name") or channel_id

    job_id = str(uuid.uuid4())
    redis = request.app.state.redis_async
    pool = request.app.state.arq_pool
    await job_hset(
        redis,
        job_id,
        workspace_id=ws,
        kind="slack_import",
        status="queued",
        progress='{"percent":0,"stage":"queued"}',
    )
    await pool.enqueue_job(
        "import_slack_channel",
        workspace_id=ws,
        source_id=sid,
        channel_id=channel_id,
        channel_name=channel_name,
        range_key=range_key,
        cutoff_date=str(cutoff_date) if cutoff_date else None,
        history_limit=history_limit,
        session_gap_seconds=session_gap,
        segmentation_mode=segmentation_mode,
        sync_cursor=source.get("sync_cursor"),
        job_id=job_id,
        _job_id=f"{job_id}:slack_import",
    )
    logger.info("slack_import_job_enqueued", workspace_id=ws, source_id=sid, job_id=job_id)
    return JSONResponse(status_code=202, content={"job_id": job_id, "status": "started"})
