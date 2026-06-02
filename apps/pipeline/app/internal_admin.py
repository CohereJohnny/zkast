"""Diagnostics + cleanup admin endpoints (Sprint 5b)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.documents_repo import list_stalled_active_documents
from app.ingestion_logs_repo import stage_latency_stats
from app.job_redis import JOB_HASH_PREFIX, arq_queue_snapshot

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["internal-admin"])


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    return v


@router.get("/internal/v1/admin/diagnostics")
async def get_admin_diagnostics(
    request: Request,
    workspace_id: Annotated[uuid.UUID | None, Query()] = None,
) -> JSONResponse:
    """Snapshot of pipeline health.

    Returns:
    - ``arq_queue_depth`` (LLEN arq:queue) and in-progress list.
    - Stalled documents (matches reconciler's signal).
    - Per-stage P50/P95 wall time from ingestion_runs.
    - Job-hash hygiene counts.
    """
    settings: Settings = request.app.state.settings
    redis = request.app.state.redis_async

    arq = await arq_queue_snapshot(redis)

    stalled: list[dict[str, Any]] = []
    try:
        import asyncio

        stalled_rows = await asyncio.to_thread(
            list_stalled_active_documents, settings.database_url, stale_seconds=90
        )
        for r in stalled_rows:
            stalled.append(
                {
                    "document_id": r.get("document_id"),
                    "workspace_id": r.get("workspace_id"),
                    "status": r.get("status"),
                    "ingestion_run_id": r.get("ingestion_run_id"),
                    "last_heartbeat_at": _iso(r.get("last_heartbeat_at")),
                    "updated_at": _iso(r.get("updated_at")),
                }
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("diagnostics_stalled_query_failed", error=str(exc))

    try:
        import asyncio

        latency_rows = await asyncio.to_thread(
            stage_latency_stats,
            settings.database_url,
            workspace_id=str(workspace_id) if workspace_id else None,
            window_hours=24,
        )
        latency = [
            {
                "status": r.get("status"),
                "p50_seconds": float(r["p50"]) if r.get("p50") is not None else None,
                "p95_seconds": float(r["p95"]) if r.get("p95") is not None else None,
                "n": int(r.get("n") or 0),
            }
            for r in latency_rows
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("diagnostics_latency_failed", error=str(exc))
        latency = []

    # Job-hash hygiene: count terminal vs in-flight hashes.
    terminal = 0
    active = 0
    try:
        cursor = 0
        scanned = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"{JOB_HASH_PREFIX}*", count=500)
            for k in keys:
                if isinstance(k, bytes):
                    k = k.decode()
                status = await redis.hget(k, "status")
                if isinstance(status, bytes):
                    status = status.decode()
                if status in ("succeeded", "failed", "cancelled"):
                    terminal += 1
                else:
                    active += 1
                scanned += 1
                if scanned >= 5000:
                    break
            if cursor == 0 or scanned >= 5000:
                break
    except Exception:  # noqa: BLE001
        pass

    return JSONResponse(
        content={
            "arq": arq,
            "stalled_documents": stalled,
            "stage_latency": latency,
            "job_hashes": {"terminal": terminal, "active": active},
        }
    )


@router.post("/internal/v1/admin/cleanup-stale-job-hashes")
async def admin_cleanup_stale_job_hashes(request: Request) -> JSONResponse:
    """Delete ``zkast:job:*`` hashes whose ``status`` is terminal.

    Filtered to safe-to-delete: ``status IN ('succeeded','failed','cancelled')``.
    Live in-flight hashes (and their replay Streams) are left alone — a naive
    bulk DEL would freeze any active UI progress drawers (Sprint 5b §B5
    footgun documented in sprint_9_notes).
    """
    redis = request.app.state.redis_async
    deleted = 0
    skipped_active = 0
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match=f"{JOB_HASH_PREFIX}*", count=500)
        for k in keys:
            if isinstance(k, bytes):
                k = k.decode()
            status = await redis.hget(k, "status")
            if isinstance(status, bytes):
                status = status.decode()
            if status in ("succeeded", "failed", "cancelled"):
                await redis.delete(k)
                # Also retire the matching Stream.
                job_id = k.removeprefix(JOB_HASH_PREFIX)
                await redis.delete(f"zkast:jobs:{job_id}:log")
                deleted += 1
            else:
                skipped_active += 1
        if cursor == 0:
            break
    return JSONResponse(content={"deleted": deleted, "skipped_active": skipped_active})
