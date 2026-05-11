"""Internal document upload and ingestion triggers."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from psycopg.errors import UniqueViolation
from starlette.responses import Response

from app.config import Settings
from app.documents_repo import (
    cleanup_expired_idempotency,
    delete_document_row,
    fetch_document,
    fetch_document_by_checksum,
    fetch_idempotency,
    fetch_workspace_id_for_document,
    insert_document,
    insert_idempotency,
    insert_ingestion_run,
    update_document,
)
from app.job_redis import job_hset
from app.storage import LocalStorage
from app.workspace_repo import fetch_pipeline_settings

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["internal-ingestion"])


class IngestionRetryBody(BaseModel):
    document_id: uuid.UUID
    from_stage: str = Field(default="parsing")


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
        _job_id=job_id,
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
    if body.from_stage != "parsing":
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

    update_document(
        db,
        document_id=doc_id,
        status="queued",
        clear_failure_reason=True,
    )

    pipe = fetch_pipeline_settings(db, ws_str)
    job_id = str(uuid.uuid4())
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
        _job_id=job_id,
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


@router.delete("/internal/v1/documents/{document_id}")
async def delete_internal_document(
    document_id: uuid.UUID,
    request: Request,
    workspace_id: Annotated[uuid.UUID, Query()],
) -> Response:
    settings: Settings = request.app.state.settings
    ws_str = str(workspace_id)
    deleted = delete_document_row(settings.database_url, workspace_id=ws_str, document_id=str(document_id))
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Document not found"}},
        )
    try:
        path = LocalStorage.absolute_path_from_uri(deleted["storage_uri"], settings.zkast_storage_root)
        path.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("storage_delete_failed", path=str(deleted.get("storage_uri")), error=str(exc))
    return Response(status_code=204)
