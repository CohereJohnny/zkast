"""Internal document upload and ingestion triggers."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from psycopg.errors import UniqueViolation
from starlette.responses import Response

from app.cascade import (
    cleanup_orphan_graph_rows,
    execute_exclusive_derivatives_delete,
    preview_document_delete,
)
from app.config import Settings
from app.documents_repo import (
    cleanup_expired_idempotency,
    delete_document_row,
    fetch_document,
    fetch_document_by_checksum,
    fetch_idempotency,
    fail_running_ingestion_runs_for_document,
    fetch_latest_ingestion_run_with_episodes,
    fetch_workspace_id_for_document,
    insert_document,
    insert_idempotency,
    insert_ingestion_run,
    is_document_ingestion_active,
    resolve_document_run_for_episodes,
    restart_ingestion_run,
    update_document,
)
from app.job_redis import job_hset
from app.notes_repo import clear_notes_for_episode_ids, clear_notes_for_ingestion_run
from app.storage import LocalStorage
from app.workspace_repo import fetch_pipeline_settings

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["internal-ingestion"])

_RETRY_STAGES = frozenset({"parsing", "generating_notes", "extracting_graph"})
_BUSY_DETAIL = {
    "error": {
        "code": "business_rule_violation",
        "message": "Document ingestion is still active; wait for it to finish or fail before retry/delete.",
    },
}


class IngestionRetryBody(BaseModel):
    document_id: uuid.UUID
    from_stage: Literal["parsing", "generating_notes", "extracting_graph"] = "parsing"


class AtomicNotesExtractBody(BaseModel):
    workspace_id: uuid.UUID
    episode_ids: list[uuid.UUID] = Field(..., min_length=1)


def _serialize_document(row: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe document row (psycopg returns datetimes; Starlette JSON cannot encode them)."""
    out: dict[str, Any] = {}
    for k, v in dict(row).items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    for k in ("id", "workspace_id", "replaces_document_id"):
        if out.get(k) is not None:
            out[k] = str(out[k])
    return out


@router.post("/internal/v1/documents")
async def post_internal_document(
    request: Request,
    workspace_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File()],
    replaces_document_id: Annotated[uuid.UUID | None, Form()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    db = settings.database_url

    ws_str = str(workspace_id)

    if idempotency_key:
        hit = fetch_idempotency(db, key=idempotency_key, workspace_id=ws_str)
        if hit:
            doc = fetch_document(db, workspace_id=ws_str, document_id=hit["document_id"])
            if doc:
                return JSONResponse(
                    status_code=202,
                    content={
                        "document": _serialize_document(doc),
                        "job_id": hit["job_id"],
                        "replayed": True,
                    },
                )

    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    storage = LocalStorage(settings.zkast_storage_root)
    try:
        storage_uri, checksum, byte_size = await storage.write_upload(
            ws_str,
            doc_id,
            file,
            max_bytes=settings.max_upload_bytes,
        )
    except ValueError as exc:
        code = str(exc)
        if code == "not_pdf":
            raise HTTPException(
                status_code=415,
                detail={"error": {"code": "unsupported_media_type", "message": "Expected a PDF file"}},
            ) from exc
        if code in ("too_large", "empty_file"):
            raise HTTPException(
                status_code=413,
                detail={"error": {"code": "payload_too_large", "message": "Upload exceeds limit"}},
            ) from exc
        raise

    dup = fetch_document_by_checksum(db, workspace_id=ws_str, checksum=checksum)
    if dup:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {"code": "conflict", "message": "Document with same checksum already exists"},
                "document": _serialize_document(dup),
            },
        )

    pipe = fetch_pipeline_settings(db, ws_str)

    try:
        doc_row = insert_document(
            db,
            document_id=doc_id,
            workspace_id=ws_str,
            original_filename=file.filename or "upload.pdf",
            mime_type="application/pdf",
            byte_size=byte_size,
            storage_uri=storage_uri,
            checksum=checksum,
            replaces_document_id=str(replaces_document_id) if replaces_document_id else None,
            status="queued",
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
    except UniqueViolation:
        existing = fetch_document_by_checksum(db, workspace_id=ws_str, checksum=checksum)
        if existing:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {"code": "conflict", "message": "Document with same checksum already exists"},
                    "document": _serialize_document(existing),
                },
            ) from None
        raise

    redis = request.app.state.redis_async
    pool = request.app.state.arq_pool
    await job_hset(
        redis,
        job_id,
        workspace_id=ws_str,
        document_id=doc_id,
        ingestion_run_id=run_id,
        kind="document_parse",
        status="queued",
        progress='{"percent":0,"stage":"queued"}',
    )

    await pool.enqueue_job(
        "parse_document",
        workspace_id=ws_str,
        document_id=doc_id,
        ingestion_run_id=run_id,
        job_id=job_id,
        _job_id=f"{job_id}:parse",
    )

    if idempotency_key:
        cleanup_expired_idempotency(db)
        insert_idempotency(
            db,
            key=idempotency_key,
            workspace_id=ws_str,
            document_id=doc_id,
            job_id=job_id,
        )

    logger.info("document_enqueued", document_id=doc_id, job_id=job_id, workspace_id=ws_str)

    return JSONResponse(
        status_code=202,
        content={"document": _serialize_document(doc_row), "job_id": job_id},
    )


@router.post("/internal/v1/ingestion-runs")
async def post_internal_ingestion_runs(body: IngestionRetryBody, request: Request) -> JSONResponse:
    if body.from_stage not in _RETRY_STAGES:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "validation_failed", "message": "Unsupported from_stage"}},
        )

    settings: Settings = request.app.state.settings
    db = settings.database_url
    doc_id = str(body.document_id)

    ws_str = fetch_workspace_id_for_document(db, doc_id)
    if not ws_str:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Document not found"}},
        )

    redis = request.app.state.redis_async
    pool = request.app.state.arq_pool
    pipe = fetch_pipeline_settings(db, ws_str)
    job_id = str(uuid.uuid4())

    if body.from_stage == "parsing":
        n_stale = fail_running_ingestion_runs_for_document(db, document_id=doc_id)
        if n_stale:
            logger.info("cancelled_stale_ingestion_runs", document_id=doc_id, count=n_stale)
        update_document(
            db,
            document_id=doc_id,
            status="queued",
            clear_failure_reason=True,
        )

        run_id = str(uuid.uuid4())
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
            workspace_id=ws_str,
            document_id=doc_id,
            ingestion_run_id=run_id,
            kind="document_parse",
            status="queued",
            progress='{"percent":0,"stage":"queued"}',
        )

        await pool.enqueue_job(
            "parse_document",
            workspace_id=ws_str,
            document_id=doc_id,
            ingestion_run_id=run_id,
            job_id=job_id,
            _job_id=f"{job_id}:parse",
        )

    elif body.from_stage == "generating_notes":
        n_stale = fail_running_ingestion_runs_for_document(db, document_id=doc_id)
        if n_stale:
            logger.info("cancelled_stale_ingestion_runs_before_notes_retry", document_id=doc_id, count=n_stale)
        run_id = fetch_latest_ingestion_run_with_episodes(db, document_id=doc_id)
        if not run_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "validation_failed",
                        "message": "No ingestion run with episodes found; retry from parsing first",
                    },
                },
            )

        clear_notes_for_ingestion_run(db, ingestion_run_id=run_id)
        restart_ingestion_run(db, run_id=run_id)
        update_document(
            db,
            document_id=doc_id,
            status="generating_notes",
            clear_failure_reason=True,
        )

        await job_hset(
            redis,
            job_id,
            workspace_id=ws_str,
            document_id=doc_id,
            ingestion_run_id=run_id,
            kind="generate_atomic_notes",
            status="queued",
            progress='{"percent":0,"stage":"generating_notes"}',
        )

        await pool.enqueue_job(
            "generate_atomic_notes",
            workspace_id=ws_str,
            document_id=doc_id,
            ingestion_run_id=run_id,
            job_id=job_id,
            episode_ids=None,
            _job_id=f"{job_id}:notes",
        )

    else:  # extracting_graph
        n_stale = fail_running_ingestion_runs_for_document(db, document_id=doc_id)
        if n_stale:
            logger.info("cancelled_stale_ingestion_runs_before_graph_retry", document_id=doc_id, count=n_stale)
        run_id = fetch_latest_ingestion_run_with_episodes(db, document_id=doc_id)
        if not run_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "validation_failed",
                        "message": "No ingestion run with episodes found; retry from parsing first",
                    },
                },
            )

        restart_ingestion_run(db, run_id=run_id)
        update_document(
            db,
            document_id=doc_id,
            status="extracting_graph",
            clear_failure_reason=True,
        )

        await job_hset(
            redis,
            job_id,
            workspace_id=ws_str,
            document_id=doc_id,
            ingestion_run_id=run_id,
            kind="extract_graph",
            status="queued",
            progress='{"percent":0,"stage":"extracting_graph"}',
        )

        await pool.enqueue_job(
            "extract_graph",
            workspace_id=ws_str,
            document_id=doc_id,
            ingestion_run_id=run_id,
            job_id=job_id,
            _job_id=f"{job_id}:graph",
        )

    doc_row = fetch_document(db, workspace_id=ws_str, document_id=doc_id)
    assert doc_row

    return JSONResponse(
        status_code=202,
        content={
            "document": _serialize_document(doc_row),
            "ingestion_run_id": run_id,
            "job_id": job_id,
        },
    )


@router.post("/internal/v1/extract/atomic-notes")
async def post_extract_atomic_notes(body: AtomicNotesExtractBody, request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    db = settings.database_url
    ws_str = str(body.workspace_id)
    ep_ids = [str(e) for e in body.episode_ids]

    resolved = resolve_document_run_for_episodes(db, workspace_id=ws_str, episode_ids=ep_ids)
    if not resolved:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "validation_failed",
                    "message": "episode_ids must exist in workspace and share one document + ingestion run",
                },
            },
        )

    doc_id, run_id = resolved
    if is_document_ingestion_active(db, document_id=doc_id):
        raise HTTPException(status_code=409, detail=_BUSY_DETAIL)

    clear_notes_for_episode_ids(db, episode_ids=ep_ids)
    restart_ingestion_run(db, run_id=run_id)
    update_document(
        db,
        document_id=doc_id,
        status="generating_notes",
        clear_failure_reason=True,
    )

    job_id = str(uuid.uuid4())
    redis = request.app.state.redis_async
    pool = request.app.state.arq_pool
    await job_hset(
        redis,
        job_id,
        workspace_id=ws_str,
        document_id=doc_id,
        ingestion_run_id=run_id,
        kind="generate_atomic_notes",
        status="queued",
        progress='{"percent":0,"stage":"generating_notes"}',
    )

    await pool.enqueue_job(
        "generate_atomic_notes",
        workspace_id=ws_str,
        document_id=doc_id,
        ingestion_run_id=run_id,
        job_id=job_id,
        episode_ids=ep_ids,
        _job_id=f"{job_id}:notes",
    )

    doc_row = fetch_document(db, workspace_id=ws_str, document_id=doc_id)
    assert doc_row

    return JSONResponse(
        status_code=202,
        content={
            "document": _serialize_document(doc_row),
            "ingestion_run_id": run_id,
            "job_id": job_id,
        },
    )


@router.get("/internal/v1/documents/{document_id}/delete-preview")
async def get_document_delete_preview(
    document_id: uuid.UUID,
    request: Request,
    workspace_id: Annotated[uuid.UUID, Query()],
    cascade: Annotated[str, Query()] = "exclusive_derivatives",
) -> JSONResponse:
    _ = cascade  # reserved for parity with external API
    settings: Settings = request.app.state.settings
    db = settings.database_url
    ws_str = str(workspace_id)
    doc_id = str(document_id)

    doc = fetch_document(db, workspace_id=ws_str, document_id=doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Document not found"}},
        )

    preview = preview_document_delete(db, workspace_id=ws_str, document_id=doc_id)
    return JSONResponse(content=preview)


@router.delete("/internal/v1/documents/{document_id}")
async def delete_internal_document(
    document_id: uuid.UUID,
    request: Request,
    workspace_id: Annotated[uuid.UUID, Query()],
    cascade: Annotated[str, Query()] = "document_only",
    force: Annotated[bool, Query()] = False,
) -> Response:
    if cascade not in ("document_only", "exclusive_derivatives"):
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "validation_failed", "message": "cascade must be document_only or exclusive_derivatives"}},
        )

    settings: Settings = request.app.state.settings
    ws_str = str(workspace_id)
    doc_id = str(document_id)

    doc = fetch_document(settings.database_url, workspace_id=ws_str, document_id=doc_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Document not found"}},
        )

    if is_document_ingestion_active(settings.database_url, document_id=doc_id):
        if not force:
            raise HTTPException(status_code=409, detail=_BUSY_DETAIL)
        # User opted in to cancel-then-delete. Mark any in-flight ingestion runs as cancelled
        # and move the document to a terminal status so the busy gate no longer fires. The
        # background worker checks document status before writing, so leftover task progress
        # against a deleted row is harmless.
        fail_running_ingestion_runs_for_document(settings.database_url, document_id=doc_id)
        update_document(
            settings.database_url,
            document_id=doc_id,
            status="failed",
            failure_reason="cancelled_by_delete",
        )
        logger.info("document_force_delete_cancel", document_id=doc_id, workspace_id=ws_str)

    if cascade == "exclusive_derivatives":
        execute_exclusive_derivatives_delete(
            settings.database_url,
            workspace_id=ws_str,
            document_id=doc_id,
        )

    deleted = delete_document_row(settings.database_url, workspace_id=ws_str, document_id=doc_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Document not found"}},
        )
    if cascade == "exclusive_derivatives":
        # Run AFTER the document row is gone, so the ON DELETE CASCADE on
        # episodes has already pruned entity_episodes/note_episodes — only
        # rows that are truly orphaned now get removed.
        cleanup = cleanup_orphan_graph_rows(settings.database_url, workspace_id=ws_str)
        logger.info(
            "document_delete_orphans_cleaned",
            document_id=doc_id,
            workspace_id=ws_str,
            removed_entities=cleanup["removed_entities"],
            removed_relationships=cleanup["removed_relationships"],
        )
    try:
        path = LocalStorage.absolute_path_from_uri(deleted["storage_uri"], settings.zkast_storage_root)
        path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("storage_delete_failed", path=str(deleted.get("storage_uri")), error=str(exc))
    return Response(status_code=204)
