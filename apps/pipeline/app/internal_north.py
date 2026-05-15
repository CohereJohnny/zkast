"""Internal HTTP API for North agent sync, conversation cache, import, dreaming."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.documents_repo import (
    fetch_document_by_checksum,
    insert_document,
    insert_ingestion_run,
)
from app.job_redis import job_hset
from app.north_client import NorthClient
from app.north_repo import (
    fetch_conversation_cache,
    fetch_north_agent,
    list_conversation_cache,
    list_north_agents,
    upsert_conversation_cache,
    upsert_north_agent,
)
from app.secrets import decrypt
from app.storage import LocalStorage
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
    except Exception as exc:  # noqa: BLE001
        logger.warning("north_list_agents_failed", error=str(exc))
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "north_upstream_error", "message": str(exc)[:500]}},
        ) from exc

    saved: list[dict[str, Any]] = []
    for item in remote:
        ext = str(item.get("id") or item.get("agent_id") or "").strip()
        if not ext:
            continue
        name = str(item.get("name") or item.get("title") or item.get("display_name") or ext)[:500]
        row = upsert_north_agent(
            db,
            workspace_id=ws,
            external_agent_id=ext,
            display_name=name,
        )
        saved.append(row)
    return JSONResponse(content={"agents": saved})


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
    return JSONResponse(content={"items": rows})


@router.get("/internal/v1/workspaces/{workspace_id}/north/agents/{agent_id}/conversations")
async def get_north_conversations(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    request: Request,
    refresh: bool = False,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    db = settings.database_url
    ws = str(workspace_id)
    agent = fetch_north_agent(db, workspace_id=ws, agent_id=str(agent_id))
    if not agent:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Agent"}})

    if not refresh:
        cached = list_conversation_cache(db, agent_id=str(agent_id), limit=100)
        return JSONResponse(content={"items": cached, "source": "cache"})

    client = _north_client_from_workspace(settings, ws)
    ext = str(agent["external_agent_id"])
    try:
        pack = await client.list_conversations(agent_id=ext, cursor=agent.get("sync_cursor"), limit=50)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "north_upstream_error", "message": str(exc)[:500]}},
        ) from exc

    items = pack.get("items") or []
    for it in items:
        cid = str(it.get("id") or it.get("conversation_id") or "").strip()
        if cid:
            upsert_conversation_cache(
                db,
                workspace_id=ws,
                agent_id=str(agent_id),
                north_conversation_id=cid,
                payload=dict(it),
            )
    return JSONResponse(
        content={
            "items": items,
            "next_cursor": pack.get("next_cursor"),
        },
    )


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
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "north_upstream_error", "message": str(exc)[:500]}},
        ) from exc

    upsert_conversation_cache(
        db,
        workspace_id=ws,
        agent_id=aid,
        north_conversation_id=conversation_id,
        payload=dict(conv),
    )

    raw_bytes = json.dumps(conv, ensure_ascii=False).encode("utf-8")
    checksum = hashlib.sha256(raw_bytes).hexdigest()
    dup = fetch_document_by_checksum(db, workspace_id=ws, checksum=checksum)
    if dup:
        return JSONResponse(
            status_code=200,
            content={"document": dup, "job_id": None, "deduped": True},
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

    import_settings = dict(agent.get("import_settings") or {})
    north_meta: dict[str, Any] = {
        "north_external_agent_id": str(agent.get("external_agent_id")),
        "agent_display_name": str(agent.get("display_name") or ""),
        "conversation_title": str(conv.get("title") or conv.get("name") or conversation_id),
        "conversation_type": str(conv.get("type") or conv.get("conversation_type") or ""),
    }

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
        raw_transcript_json=conv if isinstance(conv, dict) else {"messages": conv},
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
        content={"document": doc_row, "job_id": job_id},
    )


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

    pool = request.app.state.arq_pool
    dj = str(uuid.uuid4())
    await pool.enqueue_job(
        "run_dreaming_job",
        workspace_id=ws,
        agent_id=aid,
        _job_id=f"dream:{aid}:{dj}",
    )
    return JSONResponse(status_code=202, content={"enqueued": True, "client_token": dj})


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
