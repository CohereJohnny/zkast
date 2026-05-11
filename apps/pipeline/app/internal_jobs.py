"""Internal job polling and SSE."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.job_redis import job_hgetall
from app.jobs_stream import sse_job_events

router = APIRouter(tags=["internal-jobs"])


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
async def get_internal_job_events(job_id: str, request: Request) -> StreamingResponse:
    ws = _workspace_header(request)
    redis = request.app.state.redis_async
    raw = await job_hgetall(redis, job_id)
    if not raw or raw.get("workspace_id") != ws:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Unknown job"}},
        )

    async def gen():
        async for chunk in sse_job_events(redis, job_id):
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
