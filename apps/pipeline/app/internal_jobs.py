"""Internal job polling and SSE."""

from __future__ import annotations

import asyncio
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
from app.job_redis import (
    arq_queue_snapshot,
    decode_job_hash,
    enrich_pipeline_jobs,
    job_hgetall,
    list_workspace_jobs,
    parse_arq_in_progress_suffix,
)
from app.graphrag_reconcile import reconcile_stale_graphrag_indexes


async def _merge_arq_in_progress_jobs(
    redis: Any,
    *,
    workspace_id: str,
    jobs: list[dict[str, Any]],
    arq_in_progress: list[str],
) -> list[dict[str, Any]]:
    """Ensure worker-active arq tasks appear in the overview even if scan order missed them."""
    known = {str(j.get("job_id") or "") for j in jobs}
    merged = list(jobs)
    for entry in arq_in_progress:
        job_id, _func = parse_arq_in_progress_suffix(entry)
        if not job_id or job_id.startswith("cron:") or job_id in known:
            continue
        raw = await job_hgetall(redis, job_id)
        if not raw or raw.get("workspace_id") != workspace_id:
            continue
        row = decode_job_hash(raw)
        row["job_id"] = job_id
        merged.append(row)
        known.add(job_id)
    return merged
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

    arq = await arq_queue_snapshot(redis)

    in_progress = arq.get("in_progress") or []
    pipeline_jobs = await list_workspace_jobs(redis, workspace_id=ws, limit=40)
    pipeline_jobs = await _merge_arq_in_progress_jobs(
        redis, workspace_id=ws, jobs=pipeline_jobs, arq_in_progress=in_progress
    )
    pipeline_jobs = await asyncio.to_thread(
        enrich_pipeline_jobs,
        settings.database_url,
        pipeline_jobs,
        arq_in_progress=in_progress,
    )
    dream_jobs = list_workspace_dream_jobs(settings.database_url, workspace_id=ws, limit=30)

    return JSONResponse(
        content={
            "arq": arq,
            "pipeline_jobs": pipeline_jobs,
            "dream_jobs": dream_jobs,
        }
    )


@router.get("/internal/v1/jobs/{job_id}")
async def get_internal_job(job_id: str, request: Request) -> dict[str, Any]:
    ws = _workspace_header(request)
    redis = request.app.state.redis_async
    settings: Settings = request.app.state.settings
    if job_id.startswith("graphrag:"):
        arq = await arq_queue_snapshot(redis)
        await reconcile_stale_graphrag_indexes(
            redis,
            settings.database_url,
            arq_in_progress=arq.get("in_progress") or [],
        )
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
