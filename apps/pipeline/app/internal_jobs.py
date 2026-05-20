"""Internal job polling and SSE."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import Settings
from app.ingestion_logs_repo import (
    list_logs_for_document,
    list_logs_for_run,
)
from app.job_redis import job_hgetall, list_workspace_jobs
from app.jobs_stream import sse_job_events
from app.north_repo import list_workspace_dream_jobs

router = APIRouter(tags=["internal-jobs"])


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def _workspace_header(request: Request) -> str:
    ws = request.headers.get("x-zkast-workspace-id")
    if not ws:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "validation_failed", "message": "Missing X-Zkast-Workspace-Id"}},
        )
    return ws


def _decode_job_hash(raw: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = dict(raw)
    prog = out.get("progress")
    if isinstance(prog, str):
        try:
            out["progress"] = json.loads(prog)
        except json.JSONDecodeError:
            pass
    return out


@router.get("/internal/v1/workspaces/{workspace_id}/jobs/overview")
async def get_workspace_jobs_overview(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    """Workspace job dashboard: arq queue, Redis-tracked pipeline jobs, dream_jobs."""
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    redis = request.app.state.redis_async

    try:
        queue_depth = await redis.llen("arq:queue")
    except Exception:  # noqa: BLE001
        queue_depth = None

    try:
        in_progress = await redis.zrange("arq:in_progress", 0, -1)
        if in_progress and isinstance(in_progress[0], bytes):
            in_progress = [v.decode() for v in in_progress]
    except Exception:  # noqa: BLE001
        in_progress = []

    pipeline_jobs = await list_workspace_jobs(redis, workspace_id=ws, limit=40)
    dream_jobs = list_workspace_dream_jobs(settings.database_url, workspace_id=ws, limit=30)

    return JSONResponse(
        content={
            "arq": {"queue_depth": queue_depth, "in_progress": in_progress},
            "pipeline_jobs": pipeline_jobs,
            "dream_jobs": dream_jobs,
        }
    )


@router.get("/internal/v1/jobs/{job_id}")
async def get_internal_job(job_id: str, request: Request) -> dict[str, Any]:
    ws = _workspace_header(request)
    redis = request.app.state.redis_async
    raw = await job_hgetall(redis, job_id)
    if not raw:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Unknown job"}},
        )
    if raw.get("workspace_id") != ws:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "forbidden", "message": "Job workspace mismatch"}},
        )
    return {"job": _decode_job_hash(raw)}


@router.get("/internal/v1/jobs/{job_id}/events")
async def get_internal_job_events(
    job_id: str,
    request: Request,
    replay: Annotated[bool, Query(description="When false, skip Redis Stream replay (live tail only).")] = True,
) -> StreamingResponse:
    ws = _workspace_header(request)
    redis = request.app.state.redis_async
    raw = await job_hgetall(redis, job_id)
    if not raw or raw.get("workspace_id") != ws:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Unknown job"}},
        )

    async def gen():
        async for chunk in sse_job_events(redis, job_id, replay_history=replay):
            yield chunk

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _serialize_log_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if "ts" in out:
        out["ts"] = _iso(out["ts"])
    return out


@router.get("/internal/v1/workspaces/{workspace_id}/ingestion-runs/{run_id}/logs")
async def get_internal_ingestion_run_logs(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    level: Annotated[str | None, Query()] = None,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    rows = list_logs_for_run(
        settings.database_url,
        ingestion_run_id=str(run_id),
        limit=limit,
        level=level,
    )
    return JSONResponse(content={"items": [_serialize_log_row(r) for r in rows]})


@router.get("/internal/v1/workspaces/{workspace_id}/documents/{document_id}/logs")
async def get_internal_document_logs(
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    rows = list_logs_for_document(
        settings.database_url,
        document_id=str(document_id),
        limit=limit,
    )
    return JSONResponse(content={"items": [_serialize_log_row(r) for r in rows]})
