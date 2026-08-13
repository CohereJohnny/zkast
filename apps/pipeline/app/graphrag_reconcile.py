"""Reconcile orphaned GraphRAG index jobs after worker restarts or lost arq tasks."""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.graphrag_index_repo import list_active_graphrag_indexes, mark_failed, mark_running
from app.job_redis import (
    arq_queue_snapshot,
    job_hgetall,
    job_hset,
    parse_arq_in_progress_suffix,
    publish_job_event,
    record_log,
)

logger = structlog.get_logger(__name__)

INTERRUPTED_REASON = (
    "GraphRAG worker interrupted (container restart or job lost). Restart the build."
)


def graphrag_job_id(index_id: str) -> str:
    return f"graphrag:{index_id}"


def _parse_arq_job_ids(in_progress: list[str]) -> set[str]:
    out: set[str] = set()
    for entry in in_progress:
        job_id, _func = parse_arq_in_progress_suffix(entry)
        if job_id and not job_id.startswith("cron:"):
            out.add(job_id)
    return out


async def _mark_job_failed(
    redis: Any | None,
    *,
    job_id: str,
    index_id: str,
    database_url: str,
    reason: str,
) -> None:
    mark_failed(database_url, index_id=index_id, reason=reason)
    if not redis:
        return
    await job_hset(
        redis,
        job_id,
        status="failed",
        progress=json.dumps({"percent": 0, "stage": "graphrag_indexing", "message": reason}),
        failure_reason=reason[:2000],
    )
    await publish_job_event(
        redis,
        job_id,
        "job_failed",
        reason=reason,
        stage="graphrag_indexing",
    )
    await record_log(
        redis,
        job_id=job_id,
        level="error",
        stage="graphrag_indexing",
        message=reason,
        data={"index_id": index_id},
    )


async def reconcile_stale_graphrag_indexes(
    redis: Any | None,
    database_url: str,
    *,
    arq_in_progress: list[str] | None = None,
) -> int:
    """Mark DB + Redis GraphRAG jobs failed when no worker is running them.

    Returns the number of indexes reconciled.
    """
    if arq_in_progress is None:
        if redis is None:
            active_ids: set[str] = set()
        else:
            snap = await arq_queue_snapshot(redis)
            active_ids = _parse_arq_job_ids(snap.get("in_progress") or [])
    else:
        active_ids = _parse_arq_job_ids(arq_in_progress)

    reconciled = 0
    for row in list_active_graphrag_indexes(database_url):
        index_id = str(row["id"])
        job_id = graphrag_job_id(index_id)
        if job_id in active_ids:
            if str(row.get("status") or "") == "failed":
                mark_running(database_url, index_id=index_id)
                if redis:
                    await job_hset(redis, job_id, status="running", failure_reason="")
                    await publish_job_event(
                        redis,
                        job_id,
                        "job_resumed",
                        stage="graphrag_indexing",
                        message="GraphRAG build resumed after worker recovery",
                    )
                logger.info("graphrag_index_restored", index_id=index_id, job_id=job_id)
            continue
        raw = await job_hgetall(redis, job_id) if redis else {}
        redis_status = str(raw.get("status") or "").lower()
        if redis_status in ("succeeded", "failed", "cancelled"):
            if str(row.get("status") or "") in ("pending", "running"):
                mark_failed(database_url, index_id=index_id, reason=INTERRUPTED_REASON)
                reconciled += 1
            continue
        reason = INTERRUPTED_REASON
        await _mark_job_failed(
            redis,
            job_id=job_id,
            index_id=index_id,
            database_url=database_url,
            reason=reason,
        )
        logger.info("graphrag_index_reconciled", index_id=index_id, job_id=job_id)
        reconciled += 1
    return reconciled
