"""Dedicated graphrag-worker: MS GraphRAG batch index jobs.

Runs in its own container image (python 3.12 + graphrag + openai 2.x), isolated
from the main pipeline's openai<2 deps. This module is intentionally
**graphiti-free** — it imports only the indexer, the index repo, config, secrets,
and workspace_repo, so the graphrag image can install a minimal dep set (no
graphiti-core / langextract / cohere / pymupdf).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import structlog
from arq.connections import RedisSettings
from arq.worker import func as arq_func

from app.config import get_settings
from app.graphrag_index_repo import mark_failed, mark_ready, mark_running
from app.graphrag_indexer import EMBED_DIM, export_corpus, run_graphrag_index
from app.graphrag_log_progress import GraphragLogEvent, WORKFLOW_STAGE, parse_graphrag_log_line
from app.graphrag_reconcile import reconcile_stale_graphrag_indexes
from app.graphrag_reports_repo import persist_community_reports
from app.job_redis import emit_activity, job_hset, publish_job_event, record_log, record_metric
from app.queues import GRAPHRAG_QUEUE_NAME
from app.secrets import decrypt
from app.workspace_repo import fetch_llm_cohere_secret_row, fetch_pipeline_settings

logger = structlog.get_logger(__name__)

# Source of truth: app.graphiti_factory.COHERE_COMPAT_BASE (duplicated here to
# keep this module graphiti-free for the minimal graphrag image).
COHERE_COMPAT_BASE = "https://api.cohere.com/compatibility/v1"

TIMEOUT_GRAPHRAG_INDEX_S = 3_600
STORAGE_DIR = os.getenv("GRAPHRAG_STORAGE_DIR", "/var/zkast/graphrag")
HEARTBEAT_INTERVAL_S = 60
LOG_TAIL_INTERVAL_S = 2

GRAPHRAG_BUILD_THOUGHTS = (
    "Still indexing — GraphRAG workflows run sequentially under the hood",
)


def graphrag_job_id(index_id: str) -> str:
    return f"graphrag:{index_id}"


def _resolve_cohere_key(settings: Any, workspace_id: str) -> str | None:
    if settings.cohere_api_key and settings.cohere_api_key.strip():
        return settings.cohere_api_key.strip()
    enc = fetch_llm_cohere_secret_row(settings.database_url, workspace_id)
    if not enc:
        return None
    return decrypt(settings.master_encryption_key_bytes, enc).decode("utf-8")


async def _gr_log(
    redis: Any | None,
    *,
    job_id: str,
    message: str,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    if not redis:
        return
    await record_log(
        redis,
        job_id=job_id,
        level=level,
        stage="graphrag_indexing",
        message=message,
        data=data,
    )


async def _gr_progress(
    redis: Any | None,
    *,
    job_id: str,
    percent: int,
    message: str | None = None,
    current: int | None = None,
    total: int | None = None,
) -> None:
    if not redis:
        return
    pct = max(0, min(100, percent))
    prog: dict[str, Any] = {"percent": pct, "stage": "graphrag_indexing"}
    if current is not None:
        prog["current"] = current
    if total is not None:
        prog["total"] = total
    if message:
        prog["message"] = message
    await job_hset(redis, job_id, progress=json.dumps(prog))
    await publish_job_event(
        redis,
        job_id,
        "stage_progress",
        stage="graphrag_indexing",
        percent=pct,
        current=current,
        total=total,
        message=message,
    )


async def _gr_finish(
    redis: Any | None,
    *,
    job_id: str,
    status: str,
    stats: dict[str, Any] | None = None,
    failure_reason: str | None = None,
) -> None:
    if not redis:
        return
    pct = 100 if status == "succeeded" else 0
    await job_hset(
        redis,
        job_id,
        status=status,
        progress=json.dumps({"percent": pct, "stage": "graphrag_indexing", "stats": stats or {}}),
        failure_reason=failure_reason,
    )
    if status == "failed":
        await publish_job_event(
            redis,
            job_id,
            "job_failed",
            reason=failure_reason or "graphrag_index_failed",
            stage="graphrag_indexing",
        )
        await _gr_log(
            redis,
            job_id=job_id,
            level="error",
            message=failure_reason or "GraphRAG index build failed",
        )
    else:
        await publish_job_event(
            redis,
            job_id,
            "job_completed",
            status=status,
            stage="graphrag_indexing",
        )
        await _gr_log(
            redis,
            job_id=job_id,
            message="GraphRAG index build completed",
            data=stats,
        )


async def _emit_graphrag_log_event(
    redis: Any | None,
    *,
    job_id: str,
    event: GraphragLogEvent,
) -> None:
    if not redis:
        return
    await _gr_progress(
        redis,
        job_id=job_id,
        percent=event.percent,
        message=event.label,
        current=event.current,
        total=event.total,
    )
    if event.kind == "workflow_started":
        await publish_job_event(
            redis,
            job_id,
            "stage_started",
            stage=event.stage,
            message=event.label,
        )
    elif event.kind == "workflow_completed":
        await publish_job_event(
            redis,
            job_id,
            "stage_completed",
            stage=event.stage,
            message=event.label,
        )
        next_stage = _next_graphrag_stage(event.workflow)
        if next_stage and next_stage != event.stage:
            await publish_job_event(
                redis,
                job_id,
                "stage_started",
                stage=next_stage,
                message=event.label,
            )
    if event.kind == "workflow_started" or event.kind == "workflow_completed":
        await emit_activity(
            redis,
            job_id=job_id,
            stage=event.stage,
            kind="graphrag_workflow",
            label=event.activity_label or event.label,
            detail=event.activity_detail,
            data={
                "workflow": event.workflow,
                "current": event.current,
                "total": event.total,
            },
        )
    elif event.kind == "progress" and event.activity_label:
        await emit_activity(
            redis,
            job_id=job_id,
            stage=event.stage,
            kind="thought",
            label=event.activity_label,
            detail=event.activity_detail,
            data={
                "workflow": event.workflow,
                "current": event.current,
                "total": event.total,
            },
        )


def _next_graphrag_stage(completed_workflow: str) -> str | None:
    order = [
        "load_input_documents",
        "create_base_text_units",
        "create_final_documents",
        "extract_graph",
        "finalize_graph",
        "extract_covariates",
        "create_communities",
        "create_final_text_units",
        "create_community_reports",
        "generate_text_embeddings",
    ]
    try:
        idx = order.index(completed_workflow)
    except ValueError:
        return None
    if idx + 1 >= len(order):
        return None
    nxt = order[idx + 1]
    return WORKFLOW_STAGE.get(nxt)


async def _log_tail_loop(
    redis: Any,
    *,
    job_id: str,
    log_path: Path,
    stop: asyncio.Event,
) -> None:
    """Tail GraphRAG indexing-engine.log and emit real workflow progress."""
    offset = 0
    seen_lines: set[str] = set()
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=LOG_TAIL_INTERVAL_S)
            break
        except TimeoutError:
            pass
        if stop.is_set() or not log_path.is_file():
            continue
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) < offset:
            offset = 0
            seen_lines.clear()
        chunk = text[offset:]
        offset = len(text)
        for line in chunk.splitlines():
            key = line.strip()
            if not key or key in seen_lines:
                continue
            seen_lines.add(key)
            parsed = parse_graphrag_log_line(line)
            if parsed:
                await _emit_graphrag_log_event(redis, job_id=job_id, event=parsed)


async def _heartbeat_loop(
    redis: Any,
    *,
    job_id: str,
    stop: asyncio.Event,
) -> None:
    """Occasional alive ping — progress comes from the log tailer, not fake bumps."""
    thought_idx = 0
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_INTERVAL_S)
            break
        except TimeoutError:
            pass
        if stop.is_set():
            break
        label = GRAPHRAG_BUILD_THOUGHTS[thought_idx % len(GRAPHRAG_BUILD_THOUGHTS)]
        thought_idx += 1
        await emit_activity(
            redis,
            job_id=job_id,
            stage="building_graph",
            kind="heartbeat",
            label=label,
        )


async def run_graphrag_index_job(
    ctx: dict[str, Any],
    *,
    index_id: str,
    workspace_id: str,
    agent_id: str | None = None,
    collection_id: str | None = None,
    configuration_id: str | None = None,
    ontology_name: str | None = None,
    ontology_version: str | None = None,
    max_docs: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    db = settings.database_url
    redis = ctx.get("redis")
    job_id = graphrag_job_id(index_id)
    heartbeat_stop = asyncio.Event()
    heartbeat_task: asyncio.Task[None] | None = None
    log_tail_task: asyncio.Task[None] | None = None

    mark_running(db, index_id=index_id)
    if redis:
        await job_hset(
            redis,
            job_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            collection_id=collection_id,
            graphrag_index_id=index_id,
            kind="graphrag_index",
            status="running",
            progress='{"percent":5,"stage":"graphrag_indexing"}',
        )
        await publish_job_event(redis, job_id, "stage_started", stage="graphrag_indexing")
        await emit_activity(
            redis,
            job_id=job_id,
            stage="graphrag_indexing",
            label="Gathering documents from this memory space…",
            data={"index_id": index_id, "agent_id": agent_id, "collection_id": collection_id},
        )
        await _gr_log(
            redis,
            job_id=job_id,
            message="GraphRAG index build started",
            data={"index_id": index_id, "agent_id": agent_id, "collection_id": collection_id},
        )
        await _gr_progress(redis, job_id=job_id, percent=5, message="Starting")
        heartbeat_task = asyncio.create_task(
            _heartbeat_loop(redis, job_id=job_id, stop=heartbeat_stop)
        )

    root = Path(STORAGE_DIR) / index_id

    try:
        api_key = _resolve_cohere_key(settings, workspace_id)
        if not api_key:
            raise RuntimeError("No Cohere API key configured for this workspace")
        pipe = fetch_pipeline_settings(db, workspace_id)
        chat_model = str(pipe.get("large_model") or "command-a-plus-05-2026")
        embed_model = str(pipe.get("embed_model") or "embed-v4.0")

        await _gr_log(redis, job_id=job_id, message="Exporting corpus from memory space…")
        await _gr_progress(redis, job_id=job_id, percent=10, message="Exporting corpus")

        documents = export_corpus(
            db, workspace_id=workspace_id, agent_id=agent_id, collection_id=collection_id, max_docs=max_docs
        )
        if not documents:
            raise RuntimeError("No corpus to index for the selected scope")

        await _gr_log(
            redis,
            job_id=job_id,
            message=f"Exported {len(documents)} document(s) for indexing",
            data={"documents": len(documents), "max_docs": max_docs},
        )
        if redis:
            await emit_activity(
                redis,
                job_id=job_id,
                stage="graphrag_indexing",
                kind="graphrag_workflow",
                label=f"Corpus ready — {len(documents)} documents to index",
                detail="Starting entity extraction and community detection",
                data={"documents": len(documents)},
            )
        await _gr_progress(
            redis,
            job_id=job_id,
            percent=12,
            current=len(documents),
            total=len(documents),
            message="Corpus ready",
        )
        if redis:
            await record_metric(
                redis,
                job_id=job_id,
                name="document_count",
                value=len(documents),
                stage="graphrag_indexing",
            )

        root.mkdir(parents=True, exist_ok=True)
        log_path = root / "logs" / "indexing-engine.log"
        if redis:
            log_tail_task = asyncio.create_task(
                _log_tail_loop(redis, job_id=job_id, log_path=log_path, stop=heartbeat_stop)
            )
        os.environ["GRAPHRAG_API_KEY"] = api_key
        logger.info(
            "graphrag_index_start",
            index_id=index_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            documents=len(documents),
        )
        await _gr_log(
            redis,
            job_id=job_id,
            message=(
                f"Running GraphRAG build_index ({chat_model} / {embed_model}) — "
                "this may take several minutes"
            ),
            data={"chat_model": chat_model, "embed_model": embed_model, "root": str(root)},
        )
        await _gr_progress(redis, job_id=job_id, percent=15, message="Building index")
        if redis:
            await emit_activity(
                redis,
                job_id=job_id,
                stage="graphrag_indexing",
                kind="graphrag_workflow",
                label=f"Running GraphRAG build_index on {len(documents)} documents",
                detail=f"{chat_model} · {embed_model}",
            )

        result = await run_graphrag_index(
            root=root,
            documents=documents,
            base_url=COHERE_COMPAT_BASE,
            chat_model=chat_model,
            embed_model=embed_model,
            embed_dim=EMBED_DIM,
        )

        for wf in result["stats"].get("failed_workflows") or []:
            await _gr_log(
                redis,
                job_id=job_id,
                level="warning",
                message=f"Workflow reported errors: {wf}",
            )

        stats = result["stats"]
        if redis:
            for key in ("entities", "relationships", "communities", "community_reports", "text_units"):
                val = stats.get(key)
                if isinstance(val, (int, float)) and val:
                    await record_metric(
                        redis,
                        job_id=job_id,
                        name=key,
                        value=int(val),
                        stage="graphrag_indexing",
                    )

        if result["ok"]:
            n_reports = persist_community_reports(
                db,
                graphrag_index_id=index_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                reports=result.get("community_reports", []),
            )
            mark_ready(db, index_id=index_id, artifact_uri=result["artifact_uri"], stats=stats)
            try:
                from app.usage_events_repo import insert_usage_event

                insert_usage_event(
                    db,
                    workspace_id=workspace_id,
                    usage_source="graphrag",
                    agent_id=agent_id,
                    job_id=job_id,
                    stage="graphrag_indexing",
                    tokens_in=int(stats.get("llm_tokens_in") or 0),
                    tokens_out=int(stats.get("llm_tokens_out") or 0),
                    metadata={
                        "graphrag_index_id": index_id,
                        "documents": stats.get("documents"),
                        "entities": stats.get("entities"),
                        "relationships": stats.get("relationships"),
                        "communities": stats.get("communities"),
                        "community_reports": stats.get("community_reports"),
                    },
                    allow_zero_tokens=True,
                )
            except Exception:  # noqa: BLE001
                logger.warning("graphrag_usage_event_failed", index_id=index_id)
            logger.info(
                "graphrag_index_ready", index_id=index_id, reports=n_reports, stats=stats
            )
            await _gr_log(
                redis,
                job_id=job_id,
                message=(
                    f"Index ready — {stats.get('entities', 0)} entities, "
                    f"{stats.get('relationships', 0)} relationships, "
                    f"{stats.get('community_reports', 0)} community reports"
                ),
                data={**stats, "reports_persisted": n_reports},
            )
            if redis:
                await emit_activity(
                    redis,
                    job_id=job_id,
                    stage="graphrag_indexing",
                    kind="graphrag_workflow",
                    label=(
                        f"Index ready — {stats.get('entities', 0)} entities across "
                        f"{stats.get('community_reports', 0)} community reports"
                    ),
                    detail=f"Persisted {n_reports} reports for global-search retrieval",
                    data=stats,
                )
            await _gr_finish(redis, job_id=job_id, status="succeeded", stats=stats)
        else:
            failed = ", ".join(stats.get("failed_workflows", []))
            reason = f"GraphRAG workflows failed: {failed}"
            mark_failed(db, index_id=index_id, reason=reason)
            await _gr_finish(redis, job_id=job_id, status="failed", stats=stats, failure_reason=reason)
        return result
    except Exception as exc:  # noqa: BLE001
        reason = f"{type(exc).__name__}: {exc}"
        logger.warning("graphrag_index_failed", index_id=index_id, error=str(exc))
        mark_failed(db, index_id=index_id, reason=reason)
        await _gr_finish(redis, job_id=job_id, status="failed", failure_reason=reason)
        raise
    finally:
        heartbeat_stop.set()
        for task in (heartbeat_task, log_tail_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


async def graphrag_worker_startup(ctx: dict[str, Any]) -> None:
    """Reconcile orphaned GraphRAG indexes after worker restarts."""
    settings = get_settings()
    redis = ctx.get("redis")
    try:
        n = await reconcile_stale_graphrag_indexes(redis, settings.database_url)
        if n:
            logger.info("graphrag_worker_startup_reconciled", count=n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("graphrag_worker_startup_reconcile_failed", error=str(exc))


def _redis_settings() -> RedisSettings:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    rs = RedisSettings.from_dsn(url)
    rs.conn_timeout = 10
    return rs


class GraphragWorkerSettings:
    """arq worker consuming the dedicated GraphRAG queue."""

    queue_name = GRAPHRAG_QUEUE_NAME
    redis_settings = _redis_settings()
    on_startup = graphrag_worker_startup
    functions = [arq_func(run_graphrag_index_job, timeout=TIMEOUT_GRAPHRAG_INDEX_S, max_tries=1)]
    job_timeout = TIMEOUT_GRAPHRAG_INDEX_S
    # Index runs are heavy + sequential; one at a time.
    max_jobs = int(os.getenv("GRAPHRAG_WORKER_MAX_JOBS", "1"))
