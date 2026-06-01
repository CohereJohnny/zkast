"""Internal HTTP API for Slack connect, channel registration, threads, and import.

Connect → list channels → register channel → list/cache threads → import a
channel's conversation units (threads + session windows) into the shared
ingestion spine (parse → notes → graph). See specs/openspecs/slack-source.md.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.documents_repo import (
    fetch_document_by_checksum,
    insert_document,
    insert_ingestion_run,
)
from app.job_redis import job_hset
from app.north_repo import list_north_agents, upsert_north_agent
from app.secrets import decrypt, encrypt
from app.slack_checksum import slack_unit_content_checksum, slack_unit_ingest_hash
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
    update_source_sync_state,
    upsert_slack_connection,
    upsert_slack_conversation_cache,
)
from app.slack_transcript import DEFAULT_SESSION_GAP_SECONDS, build_conversation_units
from app.storage import LocalStorage
from app.workspace_repo import fetch_pipeline_settings

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


_RANGE_DAYS: dict[str, int] = {
    "last_30_days": 30,
    "last_90_days": 90,
    "last_180_days": 180,
    "last_365_days": 365,
}


def _compute_oldest_ts(
    *,
    range_key: str,
    cutoff_date: str | None,
    sync_cursor: str | None,
) -> str | None:
    """Resolve an import range to a Slack ``oldest`` timestamp (epoch seconds).

    - ``all`` → None (full history).
    - ``since_last`` → the stored high-water mark (only newer messages).
    - ``last_N_days`` → now − N days.
    - ``custom`` → start of ``cutoff_date`` (YYYY-MM-DD).
    """
    key = (range_key or "last_90_days").strip().lower()
    if key == "all":
        return None
    if key == "since_last":
        return sync_cursor or None
    if key == "custom" and cutoff_date:
        try:
            dt = datetime.fromisoformat(cutoff_date)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return f"{dt.timestamp():.6f}"
        except ValueError:
            return None
    days = _RANGE_DAYS.get(key, 90)
    return f"{time.time() - days * 86400:.6f}"


async def _fetch_channel_units(
    client: SlackClient,
    *,
    channel_id: str,
    channel_name: str,
    history_limit: int,
    session_gap_seconds: int,
    oldest: str | None = None,
) -> list[dict[str, Any]]:
    """Pull channel history + thread replies and segment into units."""
    roots = await client.channel_history(
        channel_id=channel_id, limit=history_limit, oldest=oldest
    )
    user_names: dict[str, str] = {}
    try:
        user_names = build_user_name_map(await client.list_users())
    except (SlackAuthError, SlackApiError) as exc:
        logger.info("slack_user_resolution_skipped", error=str(exc))

    replies_by_thread_ts: dict[str, list[dict[str, Any]]] = {}
    for msg in roots:
        ts = str(msg.get("thread_ts") or msg.get("ts") or "")
        if int(msg.get("reply_count") or 0) > 0 and ts:
            try:
                replies_by_thread_ts[ts] = await client.thread_replies(
                    channel_id=channel_id, thread_ts=ts
                )
            except (SlackAuthError, SlackApiError) as exc:
                logger.info("slack_thread_replies_skipped", thread_ts=ts, error=str(exc))

    return build_conversation_units(
        channel_id=channel_id,
        channel_name=channel_name,
        root_messages=roots,
        replies_by_thread_ts=replies_by_thread_ts,
        user_names=user_names,
        session_gap_seconds=session_gap_seconds,
    )


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
    """Import a channel's conversation units (threads + session windows).

    Each unit becomes a ``slack_conversation`` document scoped to the channel's
    memory source, then runs the shared parse → notes → graph pipeline.
    Idempotent per unit via a content checksum.
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
    history_limit = int(body.get("history_limit") or 500)
    history_limit = max(1, min(history_limit, 1000))
    session_gap = int(body.get("session_gap_seconds") or DEFAULT_SESSION_GAP_SECONDS)
    segmentation_mode = str(body.get("segmentation_mode") or "turn")
    range_key = str(body.get("range") or "last_90_days")
    cutoff_date = body.get("cutoff_date")
    oldest = _compute_oldest_ts(
        range_key=range_key,
        cutoff_date=str(cutoff_date) if cutoff_date else None,
        sync_cursor=source.get("sync_cursor"),
    )
    channel_id = source["external_agent_id"]
    channel_name = source.get("display_name") or channel_id

    client = _slack_client(settings, ws)
    try:
        units = await _fetch_channel_units(
            client,
            channel_id=channel_id,
            channel_name=channel_name,
            history_limit=history_limit,
            session_gap_seconds=session_gap,
            oldest=oldest,
        )
    except SlackAuthError as exc:
        raise HTTPException(
            status_code=401, detail={"error": {"code": "slack_auth", "message": str(exc)}}
        ) from exc
    except SlackApiError as exc:
        raise HTTPException(
            status_code=502, detail={"error": {"code": "slack_api", "message": str(exc)}}
        ) from exc

    if not units:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "slack_empty_channel",
                    "message": "No ingestible conversations after filtering (join/system/empty messages removed).",
                }
            },
        )

    db = settings.database_url
    pipe = fetch_pipeline_settings(db, ws)
    storage = LocalStorage(settings.zkast_storage_root)
    redis = request.app.state.redis_async
    pool = request.app.state.arq_pool

    created: list[dict[str, Any]] = []
    skipped = 0
    for unit in units:
        transcript = unit["transcript"]
        checksum = slack_unit_content_checksum(transcript)
        if fetch_document_by_checksum(db, workspace_id=ws, checksum=checksum):
            skipped += 1
            continue

        external_conversation_id = unit["external_conversation_id"]
        upsert_slack_conversation_cache(
            db,
            workspace_id=ws,
            source_id=sid,
            external_conversation_id=external_conversation_id,
            payload=transcript,
        )

        doc_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())

        raw_bytes = json.dumps(transcript, ensure_ascii=False).encode("utf-8")
        storage_uri, _chk, byte_size = await storage.write_north_transcript_json(
            ws, doc_id, raw_bytes, max_bytes=settings.max_upload_bytes
        )
        source_metadata = {
            "channel_id": channel_id,
            "channel_name": channel_name,
            "unit_kind": unit["kind"],
            "title": unit["title"],
            "segmentation_mode": segmentation_mode,
            "ingest_content_hash": slack_unit_ingest_hash(transcript),
        }
        doc_row = insert_document(
            db,
            document_id=doc_id,
            workspace_id=ws,
            original_filename=f"slack-{external_conversation_id}.json",
            mime_type="application/json",
            byte_size=byte_size,
            storage_uri=storage_uri,
            checksum=checksum,
            replaces_document_id=None,
            status="queued",
            source_kind="slack_conversation",
            agent_id=sid,
            external_conversation_id=external_conversation_id,
            source_metadata=source_metadata,
            raw_transcript_json=transcript,
        )
        insert_ingestion_run(
            db,
            run_id=run_id,
            document_id=doc_id,
            status="running",
            pipeline_version=settings.pipeline_version,
            llm_provider=str(pipe.get("default_llm_provider") or "cohere"),
            llm_model_small=str(pipe.get("small_model") or ""),
            llm_model_large=str(pipe.get("large_model") or ""),
            stats={"chunk_count": 0, "page_count": 0},
        )
        await job_hset(
            redis,
            job_id,
            workspace_id=ws,
            document_id=doc_id,
            ingestion_run_id=run_id,
            kind="document_parse",
            status="queued",
            progress='{"percent":0,"stage":"queued"}',
        )
        await pool.enqueue_job(
            "parse_document",
            workspace_id=ws,
            document_id=doc_id,
            ingestion_run_id=run_id,
            job_id=job_id,
            _job_id=f"{job_id}:parse",
        )
        created.append(
            {
                "document_id": doc_id,
                "job_id": job_id,
                "external_conversation_id": external_conversation_id,
                "kind": unit["kind"],
                "title": unit["title"],
            }
        )

    # Compute message-ts coverage to remember how far we've imported.
    all_ts: list[float] = []
    for unit in units:
        for m in unit["transcript"].get("messages") or []:
            try:
                all_ts.append(float(m.get("ts") or 0))
            except (TypeError, ValueError):
                continue
    newest_ts = max(all_ts) if all_ts else None
    oldest_ts = min(all_ts) if all_ts else None
    now_iso = datetime.now(tz=UTC).isoformat()

    def _iso(ts: float | None) -> str | None:
        if not ts:
            return None
        return datetime.fromtimestamp(ts, tz=UTC).isoformat()

    prior_meta = source.get("provider_metadata") if isinstance(source.get("provider_metadata"), dict) else {}
    prior_oldest = prior_meta.get("oldest_message_ts")
    # High-water mark only ever moves forward; oldest only moves backward.
    new_cursor = source.get("sync_cursor")
    if newest_ts and (not new_cursor or float(newest_ts) > float(new_cursor)):
        new_cursor = f"{newest_ts:.6f}"
    coverage_oldest = oldest_ts
    if prior_oldest:
        try:
            coverage_oldest = min(float(oldest_ts or prior_oldest), float(prior_oldest))
        except (TypeError, ValueError):
            coverage_oldest = oldest_ts

    sync_meta = {
        "last_imported_at": now_iso,
        "last_import_range": range_key,
        "last_import_created": len(created),
        "last_import_skipped": skipped,
        "newest_message_ts": f"{newest_ts:.6f}" if newest_ts else None,
        "newest_message_at": _iso(newest_ts),
        "oldest_message_ts": f"{coverage_oldest:.6f}" if coverage_oldest else None,
        "oldest_message_at": _iso(coverage_oldest),
    }
    update_source_sync_state(
        db,
        source_id=sid,
        sync_cursor=new_cursor,
        provider_metadata_merge=sync_meta,
    )

    logger.info(
        "slack_import_enqueued",
        workspace_id=ws,
        source_id=sid,
        created=len(created),
        skipped=skipped,
        range=range_key,
    )
    return JSONResponse(
        status_code=202,
        content={
            "units": len(units),
            "created": len(created),
            "skipped": skipped,
            "documents": created,
            "sync": sync_meta,
        },
    )
