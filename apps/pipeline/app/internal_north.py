"""Internal HTTP API for North agent sync, conversation cache, import, dreaming."""

from __future__ import annotations

import hashlib
import json
import uuid
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
from app.job_redis import job_hset, publish_job_event
from app.north_client import (
    NorthAuthError,
    NorthClient,
    json_safe,
    north_agent_id_for_api,
    north_conversation_row_matches_expected_agent,
    north_list_agent_display_name,
    north_list_agent_external_id,
)
from app.north_repo import (
    fetch_agent_stats,
    fetch_conversation_cache,
    fetch_dream_job,
    fetch_north_agent,
    insert_dream_job,
    list_conversation_cache,
    list_dream_job_mutations,
    list_dream_jobs,
    list_north_agents,
    update_agent_sync_cursor,
    upsert_conversation_cache,
    upsert_north_agent,
)
from app.secrets import decrypt
from app.storage import LocalStorage
from app.transcript_episodes import (
    count_north_episode_rows_from_conversation,
    north_conversation_activity_iso,
    north_conversation_preview_payload,
)
from app.workspace_repo import (
    fetch_north_bearer_secret_row,
    fetch_pipeline_settings,
    touch_north_bearer_last_used,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["internal-north"])


def _resolve_north_bearer_token(settings: Settings, database_url: str, workspace_id: str) -> str:
    enc = fetch_north_bearer_secret_row(database_url, workspace_id)
    if enc:
        return decrypt(settings.master_encryption_key_bytes, enc).decode("utf-8")
    pipe = fetch_pipeline_settings(database_url, workspace_id)
    legacy = pipe.get("north_bearer_token")
    if legacy and str(legacy).strip():
        return str(legacy).strip()
    return ""


def _north_client_from_workspace(settings: Settings, workspace_id: str) -> NorthClient:
    db = settings.database_url
    pipe = fetch_pipeline_settings(db, workspace_id)
    base = str(pipe.get("north_base_url") or "").strip()
    token = _resolve_north_bearer_token(settings, db, workspace_id)
    if not base or not token:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "north_not_configured",
                    "message": (
                        "Configure North: set pipeline_settings.north_base_url and store "
                        "a north_bearer API key (Settings), or legacy north_bearer_token in pipeline_settings."
                    ),
                },
            },
        )
    return NorthClient(base_url=base, bearer_token=token)


@router.post("/internal/v1/workspaces/{workspace_id}/north/agents/sync")
async def post_north_agents_sync(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    db = settings.database_url
    ws = str(workspace_id)
    client = _north_client_from_workspace(settings, ws)
    try:
        remote = await client.list_agents()
    except NorthAuthError as exc:
        logger.warning("north_list_agents_auth_failed", error=str(exc))
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "north_unauthorized", "message": str(exc)[:500]}},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("north_list_agents_failed", error=str(exc))
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "north_upstream_error", "message": str(exc)[:500]}},
        ) from exc

    saved: list[dict[str, Any]] = []
    for item in remote:
        ext = north_list_agent_external_id(item)
        if not ext:
            continue
        name = north_list_agent_display_name(item, external_id=ext)
        row = upsert_north_agent(
            db,
            workspace_id=ws,
            external_agent_id=ext,
            display_name=name,
        )
        saved.append(row)

    sample_keys: list[str] | None = None
    sample_field_types: dict[str, str] | None = None
    if len(remote) > 0 and len(saved) == 0:
        first = remote[0]
        if isinstance(first, dict):
            sample_keys = sorted(first.keys())[:80]
            sample_field_types = {k: type(v).__name__ for k, v in list(first.items())[:40]}
        logger.warning("north_sync_zero_registered", remote_count=len(remote), sample_keys=sample_keys)

    body: dict[str, Any] = {
        "agents": saved,
        "remote_count": len(remote),
        "registered_count": len(saved),
    }
    if sample_keys is not None:
        body["sample_top_level_keys"] = sample_keys
    if sample_field_types is not None:
        body["sample_field_types"] = sample_field_types
    return JSONResponse(content=body)


@router.post("/internal/v1/workspaces/{workspace_id}/north/test-connection")
async def post_north_test_connection(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    """Verify North URL + bearer by listing agents (side effect: touch north_bearer last_used)."""
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    try:
        client = _north_client_from_workspace(settings, ws)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    try:
        agents = await client.list_agents()
        if fetch_north_bearer_secret_row(settings.database_url, ws):
            touch_north_bearer_last_used(settings.database_url, ws)
    except NorthAuthError as exc:
        logger.warning("north_test_connection_auth_failed", error=str(exc))
        return JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "error": {"code": "north_unauthorized", "message": str(exc)[:500]},
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("north_test_connection_failed", error=str(exc))
        return JSONResponse(
            status_code=502,
            content={
                "ok": False,
                "error": {"code": "north_upstream_error", "message": str(exc)[:500]},
            },
        )

    return JSONResponse(
        content={"ok": True, "agent_count": len(agents)},
    )


@router.get("/internal/v1/workspaces/{workspace_id}/north/agents")
async def get_north_agents(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    rows = list_north_agents(settings.database_url, workspace_id=str(workspace_id))
    ws = str(workspace_id)
    return JSONResponse(
        content={
            "items": rows,
            "count": len(rows),
            "workspace_id": ws,
        },
    )


@router.get("/internal/v1/workspaces/{workspace_id}/north/agents/{agent_id}/stats")
async def get_north_agent_stats(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    db = settings.database_url
    ws = str(workspace_id)
    aid = str(agent_id)
    agent = fetch_north_agent(db, workspace_id=ws, agent_id=aid)
    if not agent:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Agent"}})
    stats = fetch_agent_stats(db, workspace_id=ws, agent_id=aid)
    return JSONResponse(content={"agent_id": aid, **stats})


@router.get("/internal/v1/workspaces/{workspace_id}/north/agents/{agent_id}/conversations")
async def get_north_conversations(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    request: Request,
    refresh: bool = Query(False, description="When true, fetch from North and upsert conversation cache."),
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    db = settings.database_url
    ws = str(workspace_id)
    agent = fetch_north_agent(db, workspace_id=ws, agent_id=str(agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Agent"}})

    if not refresh:
        cached = list_conversation_cache(db, workspace_id=ws, agent_id=str(agent_id), limit=100)
        return JSONResponse(content={"items": cached, "source": "cache"})

    client = _north_client_from_workspace(settings, ws)
    ext = str(agent["external_agent_id"])
    ext_api = north_agent_id_for_api(ext)
    try:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        last_next: str | None = None
        for _ in range(200):
            pack = await client.list_conversations(agent_id=ext_api, cursor=cursor, limit=50)
            batch = list(pack.get("items") or [])
            next_raw = pack.get("next_cursor")
            next_one: str | None = None
            if next_raw is not None:
                if isinstance(next_raw, dict):
                    inner = next_raw.get("cursor")
                    next_one = str(inner) if inner is not None else None
                else:
                    next_one = str(next_raw)
            filtered_batch: list[dict[str, Any]] = []
            for it in batch:
                if not isinstance(it, dict):
                    continue
                if not north_conversation_row_matches_expected_agent(it, ext_api):
                    continue
                cid = str(
                    it.get("id")
                    or it.get("conversation_id")
                    or it.get("conversationId")
                    or it.get("thread_id")
                    or it.get("threadId")
                    or "",
                ).strip()
                if cid:
                    upsert_conversation_cache(
                        db,
                        workspace_id=ws,
                        agent_id=str(agent_id),
                        north_conversation_id=cid,
                        payload=dict(it),
                    )
                    filtered_batch.append(dict(it))
            items.extend(filtered_batch)
            last_next = next_one
            if not next_one or not batch:
                break
            cursor = next_one
        update_agent_sync_cursor(db, agent_id=str(agent_id), cursor=last_next)
    except NorthAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "north_unauthorized", "message": str(exc)[:500]}},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "north_upstream_error", "message": str(exc)[:500]}},
        ) from exc

    return JSONResponse(
        content=json_safe(
            {
                "items": items,
                "next_cursor": last_next,
            },
        ),
    )


@router.get("/internal/v1/workspaces/{workspace_id}/north/agents/{agent_id}/conversations/{conversation_id}/preview")
async def get_north_conversation_preview(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    conversation_id: str,
    request: Request,
) -> JSONResponse:
    if not conversation_id or len(conversation_id) > 512:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "validation_failed", "message": "Invalid conversation id"}},
        )
    settings: Settings = request.app.state.settings
    db = settings.database_url
    ws = str(workspace_id)
    aid = str(agent_id)

    agent = fetch_north_agent(db, workspace_id=ws, agent_id=aid)
    if not agent:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Agent"}})

    client = _north_client_from_workspace(settings, ws)
    try:
        conv = await client.get_conversation(conversation_id)
    except NorthAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "north_unauthorized", "message": str(exc)[:500]}},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "north_upstream_error", "message": str(exc)[:500]}},
        ) from exc

    if isinstance(conv, dict):
        conv_root: dict[str, Any] = conv
    elif isinstance(conv, list):
        conv_root = {"messages": conv}
    else:
        conv_root = {"messages": []}

    preview = north_conversation_preview_payload(conv_root)
    return JSONResponse(content=json_safe(preview))


@router.post("/internal/v1/workspaces/{workspace_id}/north/agents/{agent_id}/conversations/{conversation_id}/import")
async def post_north_conversation_import(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    conversation_id: str,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    db = settings.database_url
    storage_root = settings.zkast_storage_root
    ws = str(workspace_id)
    aid = str(agent_id)

    agent = fetch_north_agent(db, workspace_id=ws, agent_id=aid)
    if not agent:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Agent"}})

    client = _north_client_from_workspace(settings, ws)
    try:
        conv = await client.get_conversation(conversation_id)
    except NorthAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "north_unauthorized", "message": str(exc)[:500]}},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "north_upstream_error", "message": str(exc)[:500]}},
        ) from exc

    if isinstance(conv, dict):
        conv_root: dict[str, Any] = conv
    elif isinstance(conv, list):
        conv_root = {"messages": conv}
    else:
        conv_root = {"messages": []}

    upsert_conversation_cache(
        db,
        workspace_id=ws,
        agent_id=aid,
        north_conversation_id=conversation_id,
        payload=conv_root,
    )

    import_settings = dict(agent.get("import_settings") or {})
    north_meta: dict[str, Any] = {
        "north_external_agent_id": str(agent.get("external_agent_id")),
        "agent_display_name": str(agent.get("display_name") or ""),
        "conversation_title": str(conv_root.get("title") or conv_root.get("name") or conversation_id),
        "conversation_type": str(conv_root.get("type") or conv_root.get("conversation_type") or ""),
    }
    activity_iso = north_conversation_activity_iso(conv_root)
    if activity_iso:
        north_meta["conversation_activity_at"] = activity_iso
    episode_count = count_north_episode_rows_from_conversation(
        conv=conv_root,
        import_settings=import_settings,
        north_metadata=north_meta,
    )
    if episode_count == 0:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "north_empty_transcript",
                    "message": (
                        "No ingestible content after applying import filters (roles, reasoning traces, "
                        "segmentation). Adjust agent import settings or choose a different conversation."
                    ),
                },
            },
        )

    raw_bytes = json.dumps(conv_root, ensure_ascii=False).encode("utf-8")
    checksum = hashlib.sha256(raw_bytes).hexdigest()
    dup = fetch_document_by_checksum(db, workspace_id=ws, checksum=checksum)
    if dup:
        return JSONResponse(
            status_code=200,
            content=json_safe({"document": dup, "job_id": None, "deduped": True}),
        )

    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    storage = LocalStorage(storage_root)
    storage_uri, _chk, byte_size = await storage.write_north_transcript_json(
        ws,
        doc_id,
        raw_bytes,
        max_bytes=settings.max_upload_bytes,
    )

    pipe = fetch_pipeline_settings(db, ws)
    doc_row = insert_document(
        db,
        document_id=doc_id,
        workspace_id=ws,
        original_filename=f"north-{conversation_id}.json",
        mime_type="application/json",
        byte_size=byte_size,
        storage_uri=storage_uri,
        checksum=checksum,
        replaces_document_id=None,
        status="queued",
        source_kind="north_conversation",
        agent_id=aid,
        north_conversation_id=conversation_id,
        north_metadata=north_meta,
        raw_transcript_json=conv_root,
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

    redis = request.app.state.redis_async
    pool = request.app.state.arq_pool
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

    logger.info("north_import_enqueued", document_id=doc_id, agent_id=aid, conversation_id=conversation_id)
    return JSONResponse(
        status_code=202,
        content=json_safe({"document": doc_row, "job_id": job_id}),
    )


@router.get("/internal/v1/workspaces/{workspace_id}/north/agents/{agent_id}/dream-jobs")
async def get_north_dream_jobs(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    aid = str(agent_id)
    agent = fetch_north_agent(settings.database_url, workspace_id=ws, agent_id=aid)
    if not agent:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Agent"}})
    items = list_dream_jobs(
        settings.database_url,
        workspace_id=ws,
        agent_id=aid,
        limit=limit,
    )
    return JSONResponse(content={"items": items})


@router.get("/internal/v1/workspaces/{workspace_id}/dream-jobs/{job_id}")
async def get_dream_job_detail(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    jid = str(job_id)
    job = fetch_dream_job(settings.database_url, workspace_id=ws, job_id=jid)
    if not job:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Dream job"}})
    mutations = list_dream_job_mutations(settings.database_url, dream_job_id=jid)
    return JSONResponse(content={"job": job, "mutations": mutations})


@router.post("/internal/v1/workspaces/{workspace_id}/north/agents/{agent_id}/dream")
async def post_north_dream(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    db = settings.database_url
    ws = str(workspace_id)
    aid = str(agent_id)
    agent = fetch_north_agent(db, workspace_id=ws, agent_id=aid)
    if not agent:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Agent"}})

    job_id = insert_dream_job(db, workspace_id=ws, agent_id=aid)
    redis = request.app.state.redis_async
    await job_hset(
        redis,
        job_id,
        workspace_id=ws,
        agent_id=aid,
        kind="dreaming",
        status="queued",
        progress='{"percent":0,"stage":"queued"}',
    )
    await publish_job_event(redis, job_id, "stage_started", stage="dreaming")
    pool = request.app.state.arq_pool
    await pool.enqueue_job(
        "run_dreaming_job",
        workspace_id=ws,
        agent_id=aid,
        job_id=job_id,
        _job_id=f"dream:{aid}:{job_id}",
    )
    return JSONResponse(
        status_code=202,
        content={"enqueued": True, "job_id": job_id, "client_token": job_id},
    )


@router.get("/internal/v1/workspaces/{workspace_id}/north/agents/{agent_id}/conversations/{conversation_id}/cache")
async def get_north_conversation_cache(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    conversation_id: str,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    payload = fetch_conversation_cache(
        settings.database_url,
        agent_id=str(agent_id),
        north_conversation_id=conversation_id,
    )
    if not payload:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Cache miss"}})
    return JSONResponse(content={"payload": payload})
