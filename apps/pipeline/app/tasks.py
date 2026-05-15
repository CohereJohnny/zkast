"""Arq worker: PDF parse -> atomic notes -> graph extraction.

Sprint 5b hardening:
- Heartbeat coroutine writes ``ingestion_runs.last_heartbeat_at`` every 10s
  so the reconciler can detect dead workers.
- ``asyncio.CancelledError`` is caught and surfaced as a clean failure
  (Python 3.8+: CancelledError is a BaseException subclass; the previous
  ``except Exception`` branch let it through and left the document zombied).
- ``arq_pool`` lookup uses ``ctx.get`` with a lazy fallback so a transient
  Redis hiccup at ``worker_startup`` no longer poisons every subsequent job.
- Reconciler cron sweeps stuck documents whose heartbeat has stalled.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timezone
from typing import Any
from uuid import uuid4

import fitz  # PyMuPDF
import psycopg
import structlog
from arq import create_pool, cron
from arq.connections import RedisSettings
from arq.worker import func as arq_func
from graphiti_core.nodes import EpisodeType

from app.chunking import chunk_page_text
from app.config import get_settings
from app.entity_schemas import (
    CUSTOM_EXTRACTION_INSTRUCTIONS,
    EDGE_TYPE_MAP,
    EDGE_TYPES,
    ENTITY_TYPES,
)
from app.evidence_extractor import (
    _normalize_name as _normalize_evidence_name,
    extract_evidence_spans,
    link_spans_to_entities,
    page_for_offset,
)
from app.evidence_repo import insert_evidence_rows
from app.chat_turn import run_chat_turn  # noqa: F401 — registered in WorkerSettings.functions
from app.documents_repo import (
    delete_episodes_for_document,
    fail_running_ingestion_runs_for_document,
    fetch_document,
    finalize_ingestion_run_success,
    list_episodes_for_ingestion_run,
    list_stalled_active_documents,
    merge_run_stats_incremental,
    merge_run_stats_warning,
    update_document,
    update_ingestion_run,
    update_ingestion_run_heartbeat,
    insert_episodes,
)
from app.entities_repo import upsert_entity_from_graphiti
from app.graphiti_factory import graphiti_for_workspace, resolve_cohere_api_key
from app.job_redis import (
    job_hset,
    publish_job_event,
    record_log,
    record_metric,
)
from app.notes_llm import generate_notes_from_episodes
from app.notes_repo import (
    add_note_link,
    fetch_note,
    insert_note,
    list_note_ids_for_document,
)
from app.relationships_repo import insert_relationship_from_graphiti
from app.storage import LocalStorage
from app.workspace_repo import fetch_pipeline_settings
from app.amem_enrich import enrich_notes_amem_batch
from app.dreaming import run_dreaming_job
from app.note_embedding_index import (
    upsert_amem_embeddings_for_notes,
    upsert_zettel_embeddings_for_notes,
)
from app.north_repo import fetch_north_agent
from app.transcript_episodes import build_episode_rows_from_transcript
from app import entities_repo

logger = structlog.get_logger(__name__)


HEARTBEAT_INTERVAL_S = 10
HEARTBEAT_STALE_THRESHOLD_S = 90
RECONCILER_LOCK_KEY = "zkast:cron:reconcile_lock"
RECONCILER_LOCK_TTL_S = 50

# Per-stage arq job_timeout budgets. Defaults are tuned for a ~20-page PDF on
# Cohere with Graphiti retries. They can be tightened later once the
# Graphiti edge-timestamp 400 storm (TD-010) is resolved.
#
# arq's default is 300s, which is too tight for ``extract_graph`` whose
# critical path is dominated by Graphiti's per-edge `_extract_edge_timestamps`
# retries (2 attempts of ~5s each per failed edge). Bumping to 40 minutes is
# generous; the heartbeat-based reconciler catches genuinely stuck jobs
# regardless of this ceiling.
TIMEOUT_PARSE_S = 600       # 10 min
TIMEOUT_NOTES_S = 1_200     # 20 min
TIMEOUT_GRAPH_S = 2_400     # 40 min
TIMEOUT_DREAM_S = 1_200     # 20 min — per-agent consolidation + LLM
# Used as the global ceiling; per-function settings override per task.
TIMEOUT_WORKER_DEFAULT_S = TIMEOUT_GRAPH_S

# If a CancelledError fires within this many seconds of the per-stage timeout,
# we classify it as a timeout (not a shutdown) for a clearer failure_reason.
TIMEOUT_CLASSIFY_WINDOW_S = 15


async def worker_startup(ctx: dict[str, Any]) -> None:
    s = get_settings()
    ctx["database_url"] = s.database_url
    ctx["zkast_storage_root"] = s.zkast_storage_root
    try:
        ctx["arq_pool"] = await create_pool(_redis_settings_for_worker())
    except Exception as exc:  # noqa: BLE001
        # Fail fast so the arq supervisor restarts the worker. The previous
        # silent swallow left ctx['arq_pool'] missing and every job blew up
        # with a confusing KeyError('arq_pool').
        logger.exception("worker_startup_failed", error=str(exc))
        raise


async def worker_shutdown(ctx: dict[str, Any]) -> None:
    pool = ctx.get("arq_pool")
    if pool is not None:
        await pool.close()


def _redis_settings_for_worker() -> RedisSettings:
    """Build the arq ``RedisSettings`` with retry-friendly defaults.

    The bare ``RedisSettings.from_dsn`` defaults (``conn_timeout=1``,
    ``conn_retries=5``, ``conn_retry_delay=1``, ``retry_on_timeout=False``)
    are too aggressive for the local Docker-on-Mac stack: a brief Redis
    pause (e.g. host CPU pressure during a sibling rebuild) can blow past
    five retries inside the 1s window and arq's ``_poll_iteration`` then
    raises ``redis.exceptions.TimeoutError`` — which kills the worker
    process. We observed exactly this in BUG-014 follow-up: a 94s cron
    delay preceded the worker's exit-1.

    With these tuned values the worker survives ~60s of Redis flakiness
    without losing jobs (they sit in the queue and resume on
    reconnect).
    """
    url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    settings = RedisSettings.from_dsn(url)
    settings.conn_timeout = 5
    settings.conn_retries = 20
    settings.conn_retry_delay = 2
    settings.retry_on_timeout = True
    return settings


async def _ensure_arq_pool(ctx: dict[str, Any]) -> Any:
    """Return ``ctx['arq_pool']`` or lazily create one with a structured warning.

    Defends against a transient Redis failure during ``worker_startup``: if
    the pool is missing we recreate it on demand so the in-flight job can
    still enqueue its successor.
    """
    pool = ctx.get("arq_pool")
    if pool is not None:
        return pool
    logger.warning("worker_startup_miss_recovered", hint="arq_pool missing; creating on demand")
    pool = await create_pool(_redis_settings_for_worker())
    ctx["arq_pool"] = pool
    return pool


class _Heartbeat:
    """Background heartbeat for an in-flight ingestion task.

    The reconciler treats ``ingestion_runs.last_heartbeat_at`` older than
    :data:`HEARTBEAT_STALE_THRESHOLD_S` as "worker died" — we tick it every
    :data:`HEARTBEAT_INTERVAL_S` seconds. Cancellation-safe via an explicit
    stop event so SIGTERM doesn't race with a half-finished write.
    """

    def __init__(self, database_url: str, ingestion_run_id: str) -> None:
        self._database_url = database_url
        self._ingestion_run_id = ingestion_run_id
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "_Heartbeat":
        # Tick once at the start so the row immediately looks alive.
        await asyncio.to_thread(
            update_ingestion_run_heartbeat,
            self._database_url,
            run_id=self._ingestion_run_id,
        )
        self._task = asyncio.create_task(self._loop(), name="ingestion-heartbeat")
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=HEARTBEAT_INTERVAL_S + 1)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=HEARTBEAT_INTERVAL_S)
            except asyncio.TimeoutError:
                pass
            if self._stop.is_set():
                return
            try:
                await asyncio.to_thread(
                    update_ingestion_run_heartbeat,
                    self._database_url,
                    run_id=self._ingestion_run_id,
                )
            except Exception as exc:  # noqa: BLE001
                # Heartbeat failures must not kill the task — log once and
                # continue. The reconciler will eventually do the right
                # thing even if our heartbeats stop landing.
                logger.warning("heartbeat_write_failed", error=str(exc))


def _describe_exception(exc: BaseException, *, max_len: int = 500) -> str:
    """Build a non-empty human-readable failure_reason from an exception.

    Some libraries (notably ``httpx``/``httpcore``) raise errors with no message
    string — ``str(httpx.ConnectError())`` is the empty string. If we wrote that
    straight to ``documents.failure_reason``, the UI shows "Job failed:" with
    nothing after the colon. This helper guarantees we always have at least the
    exception type name.

    For SDKs that dump full HTTP headers into ``str(exc)`` (Cohere's
    ``UnprocessableEntityError`` is the worst offender — its repr is hundreds
    of characters of access-control headers), we prefer the parsed JSON body's
    ``error_type`` / ``message`` fields so the chat UI shows
    ``UnprocessableEntityError: NO_VALID_RESPONSE_GENERATED — No valid
    response generated.`` rather than a wall of metadata.
    """
    name = type(exc).__name__

    # Cohere SDK errors carry a ``body`` attribute with the JSON payload.
    body = getattr(exc, "body", None)
    parsed_body: dict[str, Any] | None = None
    if isinstance(body, dict):
        parsed_body = body
    elif isinstance(body, (bytes, bytearray, str)):
        try:
            decoded = (
                body.decode() if isinstance(body, (bytes, bytearray)) else body
            )
            parsed = json.loads(decoded)
            if isinstance(parsed, dict):
                parsed_body = parsed
        except Exception:  # noqa: BLE001
            parsed_body = None

    if parsed_body:
        error_type = str(parsed_body.get("error_type") or "").strip()
        message = str(parsed_body.get("message") or "").strip()
        parts = [p for p in (error_type, message) if p]
        if parts:
            text = f"{name}: " + " — ".join(parts)
            return text[:max_len]

    msg = (str(exc) or "").strip()
    text = f"{name}: {msg}" if msg else name
    return text[:max_len]


def _classify_cancel_reason(stage: str, elapsed_s: float) -> tuple[str, dict[str, Any]]:
    """Pick a human-readable failure_reason for a CancelledError.

    arq fires a ``CancelledError`` into the task both when the worker is
    shutting down and when a per-job timeout fires (arq wraps the task in
    ``asyncio.wait_for``). From inside the task the two are indistinguishable,
    but the elapsed time is a reliable tell: if we're within
    ``TIMEOUT_CLASSIFY_WINDOW_S`` of the configured per-stage timeout, this is
    overwhelmingly a timeout, not a SIGTERM.
    """
    budget = {
        "parsing": TIMEOUT_PARSE_S,
        "generating_notes": TIMEOUT_NOTES_S,
        "extracting_graph": TIMEOUT_GRAPH_S,
    }.get(stage, TIMEOUT_WORKER_DEFAULT_S)
    extra: dict[str, Any] = {
        "elapsed_s": round(elapsed_s, 1),
        "timeout_s": budget,
    }
    if elapsed_s >= budget - TIMEOUT_CLASSIFY_WINDOW_S:
        return f"cancelled_by_job_timeout (stage {stage} ran {elapsed_s:.0f}s of {budget}s budget)", extra
    return "cancelled_by_worker_shutdown", extra


def _is_document_active(database_url: str, document_id: str) -> bool:
    """Return True while the document is in any pre-terminal status."""
    active = ("queued", "parsing", "generating_notes", "extracting_graph", "building_graph")
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            "SELECT status FROM documents WHERE id = %s::uuid LIMIT 1",
            (document_id,),
        ).fetchone()
        return bool(row and row[0] in active)


async def _mark_task_failed(
    redis: Any,
    database_url: str,
    *,
    job_id: str,
    document_id: str,
    ingestion_run_id: str,
    stage: str,
    reason: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Flip Postgres + Redis state to ``failed`` and emit the SSE event.

    Centralises the failure-marking code path so every ``except`` branch in
    every task uses the exact same fields. The original ``except Exception``
    handlers each open-coded this and one of them missed the
    ``ingestion_runs`` update, leaving a half-failed state.
    """
    truncated = reason[:500]
    try:
        await asyncio.to_thread(
            update_document,
            database_url,
            document_id=document_id,
            status="failed",
            failure_reason=truncated,
        )
        await asyncio.to_thread(
            update_ingestion_run,
            database_url,
            run_id=ingestion_run_id,
            status="failed",
            ended_at=datetime.now(UTC),
        )
    except Exception:  # noqa: BLE001
        # Postgres being temporarily unreachable should not block us from
        # publishing the failure event — the reconciler will catch up later.
        logger.exception("mark_task_failed_db_error", document_id=document_id)

    await publish_job_event(redis, job_id, "job_failed", reason=truncated, stage=stage)
    await record_log(
        redis,
        job_id=job_id,
        level="error",
        stage=stage,
        message=truncated,
        data=extra,
        database_url=database_url,
        ingestion_run_id=ingestion_run_id,
    )
    await job_hset(
        redis,
        job_id,
        status="failed",
        progress=json.dumps({"percent": 0, "stage": stage, "error": truncated}),
    )


async def _parse_north_transcript(
    ctx: dict[str, Any],
    *,
    workspace_id: str,
    document_id: str,
    ingestion_run_id: str,
    job_id: str,
    doc: dict[str, Any],
) -> None:
    """Parse cached North JSON into transcript episodes (agent scoped)."""
    redis = ctx["redis"]
    database_url: str = ctx["database_url"]

    raw: Any = doc.get("raw_transcript_json")
    if isinstance(raw, str):
        raw = json.loads(raw)
    if raw is None:
        raw = {}
    agent_id = doc.get("agent_id")
    if not agent_id:
        raise RuntimeError("north document missing agent_id")

    agent = await asyncio.to_thread(
        fetch_north_agent,
        database_url,
        workspace_id=workspace_id,
        agent_id=str(agent_id),
    )
    if not agent:
        raise RuntimeError("north agent row missing for document")

    import_settings = dict(agent.get("import_settings") or {})
    north_meta = dict(doc.get("north_metadata") or {})

    await record_log(
        redis,
        job_id=job_id,
        level="info",
        stage="parsing",
        message="Parsing North transcript into episodes",
        database_url=database_url,
        ingestion_run_id=ingestion_run_id,
    )

    await asyncio.to_thread(delete_episodes_for_document, database_url, document_id=document_id)

    transcript_root: dict[str, Any] = raw if isinstance(raw, dict) else {"messages": raw}
    rows = build_episode_rows_from_transcript(
        workspace_id=workspace_id,
        document_id=document_id,
        ingestion_run_id=ingestion_run_id,
        agent_id=str(agent_id),
        raw_transcript=transcript_root,
        import_settings=import_settings,
        north_metadata=north_meta,
    )
    if not rows:
        raise RuntimeError("North transcript produced zero episodes (check message filters)")

    await asyncio.to_thread(
        insert_episodes,
        database_url,
        workspace_id=workspace_id,
        document_id=document_id,
        ingestion_run_id=ingestion_run_id,
        rows=rows,
    )
    chunk_count = len(rows)
    await asyncio.to_thread(
        merge_run_stats_incremental,
        database_url,
        run_id=ingestion_run_id,
        extra={"chunk_count": chunk_count, "page_count": chunk_count, "stage": "parsing_done"},
    )
    await asyncio.to_thread(
        update_document,
        database_url,
        document_id=document_id,
        page_count=chunk_count,
    )
    await record_log(
        redis,
        job_id=job_id,
        level="info",
        stage="parsing",
        message=f"Parsed North transcript into {chunk_count} episodes",
        data={"chunk_count": chunk_count},
        database_url=database_url,
        ingestion_run_id=ingestion_run_id,
    )
    await publish_job_event(redis, job_id, "stage_completed", stage="parsing")

    pool = await _ensure_arq_pool(ctx)
    enqueued = await pool.enqueue_job(
        "generate_atomic_notes",
        workspace_id=workspace_id,
        document_id=document_id,
        ingestion_run_id=ingestion_run_id,
        job_id=job_id,
        _job_id=f"{job_id}:notes",
    )
    if enqueued is None:
        raise RuntimeError(
            "Failed to enqueue generate_atomic_notes — arq returned None "
            "(stage may already be queued/in-flight)."
        )
    await asyncio.to_thread(
        update_document,
        database_url,
        document_id=document_id,
        status="generating_notes",
    )
    await job_hset(
        redis,
        job_id,
        progress=json.dumps({"percent": 100, "stage": "parsing", "message": "queued_notes"}),
    )


async def parse_document(
    ctx: dict[str, Any],
    *,
    workspace_id: str,
    document_id: str,
    ingestion_run_id: str,
    job_id: str,
) -> None:
    redis = ctx["redis"]
    database_url: str = ctx["database_url"]
    storage_root: str = ctx["zkast_storage_root"]

    await job_hset(
        redis,
        job_id,
        status="running",
        workspace_id=workspace_id,
        document_id=document_id,
        ingestion_run_id=ingestion_run_id,
        kind="document_parse",
        progress=json.dumps({"percent": 0, "stage": "parsing"}),
    )
    await publish_job_event(redis, job_id, "stage_started", stage="parsing")
    _started_at = asyncio.get_event_loop().time()

    try:
        async with _Heartbeat(database_url, ingestion_run_id):
            await asyncio.to_thread(
                update_document,
                database_url,
                document_id=document_id,
                status="parsing",
            )
            doc = await asyncio.to_thread(
                fetch_document,
                database_url,
                workspace_id=workspace_id,
                document_id=document_id,
            )
            if not doc:
                raise RuntimeError("document not found")

            if str(doc.get("source_kind") or "pdf") == "north_conversation":
                await _parse_north_transcript(
                    ctx,
                    workspace_id=workspace_id,
                    document_id=document_id,
                    ingestion_run_id=ingestion_run_id,
                    job_id=job_id,
                    doc=doc,
                )
                return

            await record_log(
                redis,
                job_id=job_id,
                level="info",
                stage="parsing",
                message="Parsing PDF",
                database_url=database_url,
                ingestion_run_id=ingestion_run_id,
            )

            pipe = await asyncio.to_thread(fetch_pipeline_settings, database_url, workspace_id)
            chunk_tokens = int(pipe.get("chunk_size") or 512)
            max_chars = max(256, chunk_tokens * 4)

            path = LocalStorage.absolute_path_from_uri(doc["storage_uri"], storage_root)
            if not os.path.isfile(path):
                # B4 — storage file race: the PDF was deleted (force-delete,
                # volume reset, or path mismatch). Surface a clean message
                # instead of the previous generic RuntimeError.
                raise FileNotFoundError(path)

            def _open_doc() -> fitz.Document:
                try:
                    return fitz.open(path)
                except RuntimeError as exc:
                    # PyMuPDF raises RuntimeError for missing files too.
                    if "no such file" in str(exc).lower():
                        raise FileNotFoundError(path) from exc
                    raise

            pdf = await asyncio.to_thread(_open_doc)
            try:
                page_count = pdf.page_count
                await asyncio.to_thread(
                    update_document,
                    database_url,
                    document_id=document_id,
                    page_count=page_count,
                )

                await asyncio.to_thread(
                    delete_episodes_for_document, database_url, document_id=document_id
                )

                episode_rows: list[tuple[str, str, int, int, int, str, str | None]] = []
                sequence = 0
                throttle = max(1, page_count // 20) if page_count else 1

                for i in range(page_count):
                    page_num = i + 1
                    try:

                        def _page_text(idx: int = i) -> str:
                            return pdf.load_page(idx).get_text()

                        text = await asyncio.to_thread(_page_text)
                        for chunk_text, ps, pe in chunk_page_text(page_num, text, max_chars):
                            episode_rows.append(
                                (str(uuid4()), chunk_text, ps, pe, sequence, "pdf_chunk", None)
                            )
                            sequence += 1
                    except Exception as exc:  # noqa: BLE001
                        msg = f"page {page_num}: {exc}"
                        logger.warning("page_parse_warning", document_id=document_id, error=str(exc))
                        await asyncio.to_thread(
                            merge_run_stats_warning,
                            database_url,
                            run_id=ingestion_run_id,
                            warning=msg[:500],
                        )
                        await publish_job_event(
                            redis,
                            job_id,
                            "warning",
                            stage="parsing",
                            message=msg[:500],
                            page=page_num,
                        )
                        await record_log(
                            redis,
                            job_id=job_id,
                            level="warning",
                            stage="parsing",
                            message=msg[:500],
                            data={"page": page_num},
                            database_url=database_url,
                            ingestion_run_id=ingestion_run_id,
                        )

                    if page_num % throttle == 0 or page_num == page_count:
                        pct = int(100 * page_num / page_count) if page_count else 100
                        prog = {
                            "percent": pct,
                            "stage": "parsing",
                            "page": page_num,
                            "total_pages": page_count,
                        }
                        await job_hset(redis, job_id, progress=json.dumps(prog))
                        await publish_job_event(
                            redis,
                            job_id,
                            "stage_progress",
                            stage="parsing",
                            current=page_num,
                            total=page_count,
                            percent=pct,
                        )

                if episode_rows:
                    await asyncio.to_thread(
                        insert_episodes,
                        database_url,
                        workspace_id=workspace_id,
                        document_id=document_id,
                        ingestion_run_id=ingestion_run_id,
                        rows=episode_rows,
                    )

                chunk_count = len(episode_rows)
                await asyncio.to_thread(
                    merge_run_stats_incremental,
                    database_url,
                    run_id=ingestion_run_id,
                    extra={
                        "chunk_count": chunk_count,
                        "page_count": page_count,
                        "stage": "parsing_done",
                    },
                )
                await record_log(
                    redis,
                    job_id=job_id,
                    level="info",
                    stage="parsing",
                    message=f"Parsed {page_count} pages into {chunk_count} chunks",
                    data={"page_count": page_count, "chunk_count": chunk_count},
                    database_url=database_url,
                    ingestion_run_id=ingestion_run_id,
                )

                await publish_job_event(redis, job_id, "stage_completed", stage="parsing")

                pool = await _ensure_arq_pool(ctx)
                # arq de-dupes on `_job_id`; each pipeline stage must use a
                # unique key or the chained enqueue is silently dropped (which
                # leaves the document stuck in `generating_notes` with no work
                # ever running). Suffix the parent SSE job id per stage.
                enqueued = await pool.enqueue_job(
                    "generate_atomic_notes",
                    workspace_id=workspace_id,
                    document_id=document_id,
                    ingestion_run_id=ingestion_run_id,
                    job_id=job_id,
                    _job_id=f"{job_id}:notes",
                )
                if enqueued is None:
                    raise RuntimeError(
                        "Failed to enqueue generate_atomic_notes — arq returned None "
                        "(stage may already be queued/in-flight)."
                    )
                await asyncio.to_thread(
                    update_document,
                    database_url,
                    document_id=document_id,
                    status="generating_notes",
                )

                await job_hset(
                    redis,
                    job_id,
                    progress=json.dumps(
                        {"percent": 100, "stage": "parsing", "message": "queued_notes"}
                    ),
                )
            finally:
                await asyncio.to_thread(pdf.close)

    except asyncio.CancelledError:
        # B2.5 — both arq job_timeout and worker SIGTERM raise CancelledError
        # into the task; we use elapsed-time heuristics to distinguish the two
        # so the operator sees the right failure_reason.
        _reason, _extra = _classify_cancel_reason(
            "parsing", asyncio.get_event_loop().time() - _started_at
        )
        await _mark_task_failed(
            redis,
            database_url,
            job_id=job_id,
            document_id=document_id,
            ingestion_run_id=ingestion_run_id,
            stage="parsing",
            reason=_reason,
            extra=_extra,
        )
        raise
    except FileNotFoundError as exc:
        # B4 — storage file vanished mid-parse (force-delete + cascade).
        await _mark_task_failed(
            redis,
            database_url,
            job_id=job_id,
            document_id=document_id,
            ingestion_run_id=ingestion_run_id,
            stage="parsing",
            reason="source_pdf_deleted",
            extra={"path": str(exc)},
        )
        logger.warning("parse_document_pdf_missing", document_id=document_id, path=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("parse_document_failed", document_id=document_id, job_id=job_id)
        await _mark_task_failed(
            redis,
            database_url,
            job_id=job_id,
            document_id=document_id,
            ingestion_run_id=ingestion_run_id,
            stage="parsing",
            reason=_describe_exception(exc),
        )


async def generate_atomic_notes(
    ctx: dict[str, Any],
    *,
    workspace_id: str,
    document_id: str,
    ingestion_run_id: str,
    job_id: str,
    episode_ids: list[str] | None = None,
) -> None:
    redis = ctx["redis"]
    database_url: str = ctx["database_url"]
    settings = get_settings()

    await job_hset(
        redis,
        job_id,
        progress=json.dumps({"percent": 0, "stage": "generating_notes"}),
    )
    await publish_job_event(redis, job_id, "stage_started", stage="generating_notes")
    _started_at = asyncio.get_event_loop().time()

    try:
        # B2 — pre-check: if the document was force-deleted while we were
        # waiting in the queue, short-circuit cleanly instead of writing
        # provenance rows referencing now-deleted episodes.
        if not await asyncio.to_thread(_is_document_active, database_url, document_id):
            raise RuntimeError("Document no longer active (deleted or already failed)")

        async with _Heartbeat(database_url, ingestion_run_id):
            episodes = await asyncio.to_thread(
                list_episodes_for_ingestion_run,
                database_url,
                ingestion_run_id=ingestion_run_id,
            )
            if episode_ids:
                allow = set(episode_ids)
                episodes = [e for e in episodes if e.get("id") in allow]
            if not episodes:
                raise RuntimeError("No episodes to generate notes from (check episode_ids filter)")
            agent_ids = {str(ep["agent_id"]) for ep in episodes if ep.get("agent_id")}
            if len(agent_ids) > 1:
                raise RuntimeError(
                    "Mixed-agent episode batch: all episodes must share the same agent_id for note generation"
                )
            agent_scope: str | None = next(iter(agent_ids)) if len(agent_ids) == 1 else None
            pipe = await asyncio.to_thread(fetch_pipeline_settings, database_url, workspace_id)
            max_notes = min(500, max(1, int(pipe.get("max_notes_per_document") or 50)))
            model = str(pipe.get("large_model") or "command-a-plus-05-2026")
            streaming_enabled = bool(pipe.get("notes_llm_streaming", True))

            api_key = resolve_cohere_api_key(settings, workspace_id)
            if not api_key:
                raise RuntimeError("No Cohere API key for note generation")

            await record_log(
                redis,
                job_id=job_id,
                level="info",
                stage="generating_notes",
                message=f"Synthesising notes from {len(episodes)} chunks (max {max_notes})",
                data={"episodes": len(episodes), "max_notes": max_notes, "model": model},
                database_url=database_url,
                ingestion_run_id=ingestion_run_id,
            )

            async def _progress_cb(tokens: int) -> None:
                await record_metric(
                    redis,
                    job_id=job_id,
                    name="tokens_consumed",
                    value=tokens,
                    stage="generating_notes",
                )

            async def _warning_cb(message: str, data: dict[str, Any] | None) -> None:
                # Surface notes_llm warnings (empty stream, unparseable
                # stream fallback) into the JobLogConsole drawer so the
                # user can see "the system is recovering, not stuck".
                await record_log(
                    redis,
                    job_id=job_id,
                    level="warning",
                    stage="generating_notes",
                    message=message,
                    data=data,
                    database_url=database_url,
                    ingestion_run_id=ingestion_run_id,
                )

            note_payloads: list[dict[str, Any]] = []
            suggested_links: list[dict[str, Any]] = []
            if episodes:
                note_payloads, suggested_links = await generate_notes_from_episodes(
                    api_key=api_key,
                    model=model,
                    episodes=episodes,
                    max_notes=max_notes,
                    streaming=streaming_enabled,
                    progress_callback=_progress_cb,
                    warning_callback=_warning_cb,
                )

            created_ids: list[str] = []
            skipped = 0
            for payload in note_payloads:
                nid = str(uuid4())
                try:
                    await asyncio.to_thread(
                        insert_note,
                        database_url,
                        note_id=nid,
                        workspace_id=workspace_id,
                        title=payload["title"],
                        body=payload["body"],
                        tags=payload.get("tags") or [],
                        origin="generated",
                        created_by_user_id=None,
                        episode_ids=payload["source_episode_ids"],
                        is_user_edited=False,
                        agent_id=agent_scope,
                    )
                    created_ids.append(nid)
                except psycopg.errors.ForeignKeyViolation as fk_exc:
                    # B2 — race: episodes were deleted between our list_*
                    # call and this insert. Skip this note rather than
                    # failing the whole stage.
                    skipped += 1
                    logger.warning(
                        "note_skipped_provenance_gone",
                        document_id=document_id,
                        note_title=str(payload.get("title"))[:80],
                        error=str(fk_exc)[:200],
                    )
                    await record_log(
                        redis,
                        job_id=job_id,
                        level="warning",
                        stage="generating_notes",
                        message="Skipping note — source episode missing (likely concurrent delete)",
                        data={"note_title": str(payload.get("title"))[:120]},
                        database_url=database_url,
                        ingestion_run_id=ingestion_run_id,
                    )

            for ln in suggested_links:
                fr = ln["from"]
                to = ln["to"]
                if 0 <= fr < len(created_ids) and 0 <= to < len(created_ids):
                    try:
                        await asyncio.to_thread(
                            add_note_link,
                            database_url,
                            workspace_id=workspace_id,
                            source_note_id=created_ids[fr],
                            target_note_id=created_ids[to],
                            kind=ln.get("kind", "related"),
                            custom_label=None,
                            origin="generated",
                            link_reason=str(ln.get("link_reason") or ln.get("reason") or "")[:2000]
                            or None,
                            link_strength=float(ln.get("link_strength") or 1.0),
                        )
                    except Exception as link_exc:  # noqa: BLE001
                        logger.warning("note_link_skip", error=str(link_exc))

            embed_model = str(pipe.get("embed_model") or "embed-v4.0")
            if created_ids:
                await upsert_zettel_embeddings_for_notes(
                    api_key=api_key,
                    database_url=database_url,
                    workspace_id=workspace_id,
                    note_ids=created_ids,
                    agent_id=agent_scope,
                    embed_model=embed_model,
                )
            if created_ids:
                await enrich_notes_amem_batch(
                    api_key=api_key,
                    model=model,
                    database_url=database_url,
                    workspace_id=workspace_id,
                    note_ids=created_ids,
                )
            if created_ids:
                await upsert_amem_embeddings_for_notes(
                    api_key=api_key,
                    database_url=database_url,
                    workspace_id=workspace_id,
                    note_ids=created_ids,
                    agent_id=agent_scope,
                    embed_model=embed_model,
                )

            await asyncio.to_thread(
                merge_run_stats_incremental,
                database_url,
                run_id=ingestion_run_id,
                extra={"note_count": len(created_ids), "stage": "notes_done"},
            )
            await record_metric(
                redis,
                job_id=job_id,
                name="note_count",
                value=len(created_ids),
                stage="generating_notes",
            )
            await record_log(
                redis,
                job_id=job_id,
                level="info",
                stage="generating_notes",
                message=f"Created {len(created_ids)} notes (skipped {skipped})",
                data={"created": len(created_ids), "skipped": skipped},
                database_url=database_url,
                ingestion_run_id=ingestion_run_id,
            )

            pool = await _ensure_arq_pool(ctx)
            enqueued = await pool.enqueue_job(
                "extract_graph",
                workspace_id=workspace_id,
                document_id=document_id,
                ingestion_run_id=ingestion_run_id,
                job_id=job_id,
                _job_id=f"{job_id}:graph",
            )
            if enqueued is None:
                raise RuntimeError(
                    "Failed to enqueue extract_graph — arq returned None "
                    "(stage may already be queued/in-flight)."
                )
            await asyncio.to_thread(
                update_document,
                database_url,
                document_id=document_id,
                status="extracting_graph",
            )

            await publish_job_event(redis, job_id, "stage_completed", stage="generating_notes")
            await job_hset(
                redis,
                job_id,
                progress=json.dumps({"percent": 50, "stage": "extracting_graph"}),
            )

    except asyncio.CancelledError:
        _reason, _extra = _classify_cancel_reason(
            "generating_notes", asyncio.get_event_loop().time() - _started_at
        )
        await _mark_task_failed(
            redis,
            database_url,
            job_id=job_id,
            document_id=document_id,
            ingestion_run_id=ingestion_run_id,
            stage="generating_notes",
            reason=_reason,
            extra=_extra,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("generate_atomic_notes_failed", document_id=document_id)
        await _mark_task_failed(
            redis,
            database_url,
            job_id=job_id,
            document_id=document_id,
            ingestion_run_id=ingestion_run_id,
            stage="generating_notes",
            reason=_describe_exception(exc),
        )


async def extract_graph(
    ctx: dict[str, Any],
    *,
    workspace_id: str,
    document_id: str,
    ingestion_run_id: str,
    job_id: str,
) -> None:
    redis = ctx["redis"]
    database_url: str = ctx["database_url"]
    settings = get_settings()

    await publish_job_event(redis, job_id, "stage_started", stage="extracting_graph")
    _started_at = asyncio.get_event_loop().time()
    await asyncio.to_thread(
        update_document,
        database_url,
        document_id=document_id,
        status="building_graph",
    )

    ref = datetime.now(timezone.utc)
    counters: dict[str, int] = {
        "entity": 0,
        "edge": 0,
        "items_done": 0,
        "evidence_extracted": 0,
        "evidence_linked": 0,
    }

    # Sprint 5c Phase 2 — resolve Cohere creds + the small-model name once so
    # the per-episode LangExtract calls don't refetch from Postgres every
    # time. Evidence extraction is best-effort: if any of these are missing
    # we just skip it and the graph stage proceeds with Graphiti-only
    # extraction (no evidence rows).
    _evidence_api_key: str | None = None
    _evidence_model: str | None = None
    try:
        _evidence_api_key = await asyncio.to_thread(
            resolve_cohere_api_key, settings, workspace_id
        )
        _pipeline_for_evidence = await asyncio.to_thread(
            fetch_pipeline_settings, database_url, workspace_id
        )
        _evidence_model = str(_pipeline_for_evidence.get("small_model") or "").strip() or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("evidence_setup_failed", error=str(exc))

    try:
        # B2 — pre-check active state.
        if not await asyncio.to_thread(_is_document_active, database_url, document_id):
            raise RuntimeError("Document no longer active (deleted or already failed)")

        async with _Heartbeat(database_url, ingestion_run_id):
            graphiti = await graphiti_for_workspace(settings, workspace_id)
            episodes = await asyncio.to_thread(
                list_episodes_for_ingestion_run,
                database_url,
                ingestion_run_id=ingestion_run_id,
            )
            note_ids = await asyncio.to_thread(
                list_note_ids_for_document,
                database_url,
                workspace_id=workspace_id,
                document_id=document_id,
            )

            pipe = await asyncio.to_thread(fetch_pipeline_settings, database_url, workspace_id)
            concurrency = int(pipe.get("graph_extract_concurrency") or 4)
            concurrency = max(1, min(8, concurrency))

            total_items = sum(1 for ep in episodes if (ep.get("text") or "").strip()) + len(note_ids)
            await record_log(
                redis,
                job_id=job_id,
                level="info",
                stage="extracting_graph",
                message=(
                    f"Extracting graph from {len(episodes)} episodes + {len(note_ids)} notes "
                    f"(concurrency={concurrency})"
                ),
                data={
                    "episodes": len(episodes),
                    "notes": len(note_ids),
                    "concurrency": concurrency,
                    "total_items": total_items,
                },
                database_url=database_url,
                ingestion_run_id=ingestion_run_id,
            )

            sem = asyncio.Semaphore(concurrency)
            counters_lock = asyncio.Lock()

            async def _process_episode(idx: int, ep: dict[str, Any]) -> None:
                body = (ep.get("text") or "")[:50000]
                if not body.strip():
                    return
                async with sem:
                    res = await graphiti.add_episode(
                        name=f"pdf-chunk-{ep.get('sequence')}",
                        episode_body=body,
                        source_description=f"PDF pages {ep.get('page_start')}-{ep.get('page_end')}",
                        reference_time=ref,
                        source=EpisodeType.text,
                        group_id=workspace_id,
                        # Sprint 5c — type-constrained extraction so we
                        # stop collapsing every entity into "Concept".
                        entity_types=ENTITY_TYPES,
                        edge_types=EDGE_TYPES,
                        edge_type_map=EDGE_TYPE_MAP,
                        custom_extraction_instructions=CUSTOM_EXTRACTION_INSTRUCTIONS,
                    )
                ep_id = str(ep["id"])
                local_entities = 0
                local_edges = 0
                # ``entity_index`` keys (normalized_name, type) → canonical
                # entity uuid for this episode. Used by the LangExtract
                # evidence link step below.
                entity_index: dict[tuple[str, str], str] = {}
                for node in res.nodes:
                    try:
                        eid = await asyncio.to_thread(
                            upsert_entity_from_graphiti,
                            database_url,
                            workspace_id=workspace_id,
                            graphiti_uuid=node.uuid,
                            name=node.name,
                            labels=list(node.labels or []),
                            summary=node.summary or "",
                            attributes=dict(node.attributes or {}),
                            episode_id=ep_id,
                            note_id=None,
                        )
                        local_entities += 1
                        if eid:
                            # Index by every non-Entity label so a LangExtract
                            # span that picked a slightly different type can
                            # still match.
                            etype_keys = [
                                lab for lab in (node.labels or []) if lab and lab != "Entity"
                            ]
                            if not etype_keys:
                                etype_keys = ["Concept"]
                            norm = _normalize_evidence_name(node.name or "")
                            for k in etype_keys:
                                entity_index[(norm, k)] = eid
                    except psycopg.errors.ForeignKeyViolation:
                        # Concurrent delete removed the episode.
                        logger.warning(
                            "entity_skipped_provenance_gone",
                            episode_id=ep_id,
                            node_uuid=str(node.uuid),
                        )
                for edge in res.edges:
                    src = await asyncio.to_thread(
                        entities_repo.fetch_entity_id_for_graphiti_uuid,
                        database_url,
                        edge.source_node_uuid,
                    )
                    tgt = await asyncio.to_thread(
                        entities_repo.fetch_entity_id_for_graphiti_uuid,
                        database_url,
                        edge.target_node_uuid,
                    )
                    if not src or not tgt:
                        continue
                    try:
                        await asyncio.to_thread(
                            insert_relationship_from_graphiti,
                            database_url,
                            workspace_id=workspace_id,
                            graphiti_edge_uuid=edge.uuid,
                            source_entity_id=src,
                            target_entity_id=tgt,
                            rel_type=edge.name,
                            fact=edge.fact,
                            confidence=1.0,
                            valid_from=edge.valid_at,
                            valid_to=edge.invalid_at,
                            episode_id=ep_id,
                            note_id=None,
                        )
                        local_edges += 1
                    except psycopg.errors.ForeignKeyViolation:
                        logger.warning(
                            "relationship_skipped_provenance_gone",
                            episode_id=ep_id,
                            edge_uuid=str(edge.uuid),
                        )

                # Sprint 5c Phase 2 — LangExtract evidence linking.
                # Best-effort: any failure inside extract_evidence_spans is
                # caught at the source and returns []. We never let evidence
                # extraction block the run.
                local_evidence_extracted = 0
                local_evidence_linked = 0
                if _evidence_api_key and _evidence_model:
                    spans = await extract_evidence_spans(
                        text=body,
                        api_key=_evidence_api_key,
                        model=_evidence_model,
                    )
                    local_evidence_extracted = len(spans)
                    if spans and entity_index:
                        linked = link_spans_to_entities(spans, entity_index)
                        rows = []
                        page_default = int(ep.get("page_start") or 0)
                        for eid, span in linked:
                            rows.append(
                                {
                                    "entity_id": eid,
                                    "document_id": document_id,
                                    "episode_id": ep_id,
                                    "page": page_default
                                    + page_for_offset(span.char_start, []),
                                    "char_start": span.char_start,
                                    "char_end": span.char_end,
                                    "quote": span.quote,
                                    "attributes": span.attributes,
                                }
                            )
                        if rows:
                            try:
                                local_evidence_linked = await asyncio.to_thread(
                                    insert_evidence_rows,
                                    database_url,
                                    workspace_id=workspace_id,
                                    rows=rows,
                                )
                            except psycopg.errors.ForeignKeyViolation:
                                # Episode or document was removed mid-flight;
                                # safe to drop the evidence rows quietly.
                                logger.warning(
                                    "evidence_skipped_fk_violation",
                                    episode_id=ep_id,
                                )

                async with counters_lock:
                    counters["entity"] += local_entities
                    counters["edge"] += local_edges
                    counters["items_done"] += 1
                    counters["evidence_extracted"] += local_evidence_extracted
                    counters["evidence_linked"] += local_evidence_linked
                    items_done = counters["items_done"]
                    total_entities = counters["entity"]
                    total_edges = counters["edge"]
                    total_evidence_extracted = counters["evidence_extracted"]
                    total_evidence_linked = counters["evidence_linked"]

                evidence_suffix = ""
                if local_evidence_extracted or local_evidence_linked:
                    evidence_suffix = (
                        f", +{local_evidence_linked}/{local_evidence_extracted} evidence"
                    )
                await record_log(
                    redis,
                    job_id=job_id,
                    level="info",
                    stage="extracting_graph",
                    message=(
                        f"episode {idx + 1}/{len(episodes)}: "
                        f"+{local_entities} entities, +{local_edges} edges{evidence_suffix}"
                    ),
                    data={
                        "episode_index": idx,
                        "episode_total": len(episodes),
                        "delta_entities": local_entities,
                        "delta_edges": local_edges,
                        "delta_evidence_extracted": local_evidence_extracted,
                        "delta_evidence_linked": local_evidence_linked,
                    },
                    database_url=database_url,
                    ingestion_run_id=ingestion_run_id,
                )
                await record_metric(
                    redis,
                    job_id=job_id,
                    name="entity_count",
                    value=total_entities,
                    stage="extracting_graph",
                )
                await record_metric(
                    redis,
                    job_id=job_id,
                    name="edge_count",
                    value=total_edges,
                    stage="extracting_graph",
                )
                if _evidence_api_key and _evidence_model:
                    await record_metric(
                        redis,
                        job_id=job_id,
                        name="evidence_spans_linked",
                        value=total_evidence_linked,
                        stage="extracting_graph",
                    )
                if total_items:
                    pct = 50 + int(45 * items_done / total_items)
                    await job_hset(
                        redis,
                        job_id,
                        progress=json.dumps(
                            {
                                "percent": pct,
                                "stage": "building_graph",
                                "current": items_done,
                                "total": total_items,
                            }
                        ),
                    )

            async def _process_note(nid: str) -> None:
                note_row = await asyncio.to_thread(
                    fetch_note,
                    database_url,
                    workspace_id=workspace_id,
                    note_id=nid,
                )
                if not note_row:
                    return
                body = f"# {note_row['title']}\n\n{note_row['body']}"[:50000]
                async with sem:
                    res = await graphiti.add_episode(
                        name=f"note-{nid[:8]}",
                        episode_body=body,
                        source_description="Atomic note",
                        reference_time=ref,
                        source=EpisodeType.text,
                        group_id=workspace_id,
                        entity_types=ENTITY_TYPES,
                        edge_types=EDGE_TYPES,
                        edge_type_map=EDGE_TYPE_MAP,
                        custom_extraction_instructions=CUSTOM_EXTRACTION_INSTRUCTIONS,
                    )
                local_entities = 0
                local_edges = 0
                for node in res.nodes:
                    try:
                        await asyncio.to_thread(
                            upsert_entity_from_graphiti,
                            database_url,
                            workspace_id=workspace_id,
                            graphiti_uuid=node.uuid,
                            name=node.name,
                            labels=list(node.labels or []),
                            summary=node.summary or "",
                            attributes=dict(node.attributes or {}),
                            episode_id=None,
                            note_id=nid,
                        )
                        local_entities += 1
                    except psycopg.errors.ForeignKeyViolation:
                        logger.warning("entity_skipped_note_gone", note_id=nid)
                for edge in res.edges:
                    src = await asyncio.to_thread(
                        entities_repo.fetch_entity_id_for_graphiti_uuid,
                        database_url,
                        edge.source_node_uuid,
                    )
                    tgt = await asyncio.to_thread(
                        entities_repo.fetch_entity_id_for_graphiti_uuid,
                        database_url,
                        edge.target_node_uuid,
                    )
                    if not src or not tgt:
                        continue
                    try:
                        await asyncio.to_thread(
                            insert_relationship_from_graphiti,
                            database_url,
                            workspace_id=workspace_id,
                            graphiti_edge_uuid=edge.uuid,
                            source_entity_id=src,
                            target_entity_id=tgt,
                            rel_type=edge.name,
                            fact=edge.fact,
                            confidence=1.0,
                            valid_from=edge.valid_at,
                            valid_to=edge.invalid_at,
                            episode_id=None,
                            note_id=nid,
                        )
                        local_edges += 1
                    except psycopg.errors.ForeignKeyViolation:
                        logger.warning("relationship_skipped_note_gone", note_id=nid)

                async with counters_lock:
                    counters["entity"] += local_entities
                    counters["edge"] += local_edges
                    counters["items_done"] += 1
                    items_done = counters["items_done"]

                await record_log(
                    redis,
                    job_id=job_id,
                    level="info",
                    stage="building_graph",
                    message=f"note {nid[:8]}: +{local_entities} entities, +{local_edges} edges",
                    data={"note_id": nid, "delta_entities": local_entities, "delta_edges": local_edges},
                    database_url=database_url,
                    ingestion_run_id=ingestion_run_id,
                )
                if total_items:
                    pct = 50 + int(45 * items_done / total_items)
                    await job_hset(
                        redis,
                        job_id,
                        progress=json.dumps(
                            {
                                "percent": pct,
                                "stage": "building_graph",
                                "current": items_done,
                                "total": total_items,
                            }
                        ),
                    )

            # ``return_exceptions=True`` keeps a single transient Cohere /
            # Graphiti failure from killing the whole batch (BUG-008). We tally
            # per-episode failures, log them, and only fail the job if zero
            # episodes succeeded.
            ep_results = await asyncio.gather(
                *(_process_episode(i, ep) for i, ep in enumerate(episodes)),
                return_exceptions=True,
            )
            note_results = await asyncio.gather(
                *(_process_note(nid) for nid in note_ids),
                return_exceptions=True,
            )
            failures = [
                r for r in (*ep_results, *note_results) if isinstance(r, BaseException)
            ]
            successes = (len(ep_results) + len(note_results)) - len(failures)
            if failures:
                # Re-raise CancelledError immediately — never swallow it (it
                # comes from arq timeout or worker shutdown).
                for exc in failures:
                    if isinstance(exc, asyncio.CancelledError):
                        raise exc
                first = failures[0]
                await record_log(
                    redis,
                    job_id=job_id,
                    level="warning",
                    stage="extracting_graph",
                    message=(
                        f"{len(failures)} of {len(ep_results) + len(note_results)} items "
                        f"failed during extraction (first: {type(first).__name__}: {str(first) or 'no message'})"
                    ),
                    data={
                        "failures": len(failures),
                        "total": len(ep_results) + len(note_results),
                        "first_error_type": type(first).__name__,
                    },
                    database_url=database_url,
                    ingestion_run_id=ingestion_run_id,
                )
                if successes == 0:
                    # Total wipeout — surface the first exception so the
                    # operator-facing failure_reason is informative.
                    raise failures[0]

            entity_count = counters["entity"]
            edge_count = counters["edge"]

            await asyncio.to_thread(
                merge_run_stats_incremental,
                database_url,
                run_id=ingestion_run_id,
                extra={
                    "graph_entity_extractions": entity_count,
                    "graph_edge_extractions": edge_count,
                    "stage": "graph_done",
                },
            )
            await asyncio.to_thread(
                finalize_ingestion_run_success,
                database_url,
                run_id=ingestion_run_id,
                extra={
                    "graph_entity_extractions": entity_count,
                    "graph_edge_extractions": edge_count,
                },
            )
            await asyncio.to_thread(
                update_document,
                database_url,
                document_id=document_id,
                status="ready",
                clear_failure_reason=True,
            )

            await record_log(
                redis,
                job_id=job_id,
                level="info",
                stage="building_graph",
                message=(
                    f"Graph build complete: {entity_count} entities, {edge_count} edges"
                ),
                data={"entities": entity_count, "edges": edge_count},
                database_url=database_url,
                ingestion_run_id=ingestion_run_id,
            )
            await publish_job_event(redis, job_id, "stage_completed", stage="building_graph")
            await publish_job_event(redis, job_id, "job_completed", status="succeeded")
            await job_hset(
                redis,
                job_id,
                status="succeeded",
                progress=json.dumps({"percent": 100, "stage": "ready"}),
            )

    except asyncio.CancelledError:
        _reason, _extra = _classify_cancel_reason(
            "extracting_graph", asyncio.get_event_loop().time() - _started_at
        )
        await _mark_task_failed(
            redis,
            database_url,
            job_id=job_id,
            document_id=document_id,
            ingestion_run_id=ingestion_run_id,
            stage="extracting_graph",
            reason=_reason,
            extra=_extra,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("extract_graph_failed", document_id=document_id)
        await _mark_task_failed(
            redis,
            database_url,
            job_id=job_id,
            document_id=document_id,
            ingestion_run_id=ingestion_run_id,
            stage="extracting_graph",
            reason=_describe_exception(exc),
        )


async def reconcile_stuck_documents(ctx: dict[str, Any]) -> None:
    """B1 — flip zombie documents to ``failed`` when their heartbeat dies.

    Runs every minute. Uses a Redis NX lock so multiple worker replicas don't
    double-mark. Any document in an active status whose ingestion_run
    heartbeat is older than :data:`HEARTBEAT_STALE_THRESHOLD_S` becomes
    ``failed`` with ``failure_reason='worker_crashed_during_<stage>'``.
    """
    database_url: str = ctx["database_url"]
    redis = ctx["redis"]
    try:
        acquired = await redis.set(
            RECONCILER_LOCK_KEY,
            "1",
            ex=RECONCILER_LOCK_TTL_S,
            nx=True,
        )
    except Exception:  # noqa: BLE001
        acquired = True  # be permissive if redis is briefly weird

    if not acquired:
        return

    try:
        stalled = await asyncio.to_thread(
            list_stalled_active_documents,
            database_url,
            stale_seconds=HEARTBEAT_STALE_THRESHOLD_S,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("reconcile_query_failed", error=str(exc))
        return

    if not stalled:
        return

    logger.warning("reconciling_stuck_documents", count=len(stalled))
    for row in stalled:
        document_id = str(row["document_id"])
        stage = str(row["status"])
        ingestion_run_id = str(row.get("ingestion_run_id") or "")
        try:
            await asyncio.to_thread(
                fail_running_ingestion_runs_for_document,
                database_url,
                document_id=document_id,
            )
            await asyncio.to_thread(
                update_document,
                database_url,
                document_id=document_id,
                status="failed",
                failure_reason=f"worker_crashed_during_{stage}",
            )
            logger.warning(
                "reconciled_stuck_document",
                document_id=document_id,
                previous_status=stage,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("reconcile_update_failed", document_id=document_id, error=str(exc))


# Sprint 6 — chat turn task timeout. Generous because of Cohere stream
# variability + non-streaming fallback round-trip; safe because the user
# can always click "Stop" to cancel cooperatively.
TIMEOUT_CHAT_TURN_S = 1_800


class WorkerSettings:
    redis_settings = _redis_settings_for_worker()
    # Per-function timeouts override arq's 300s default. ``extract_graph``
    # gets the most generous budget because Graphiti's edge-timestamp
    # extractor currently retries 2× per failed edge against Cohere (TD-010).
    # Sprint 6 added ``run_chat_turn`` for grounded chat.
    functions = [
        arq_func(parse_document, timeout=TIMEOUT_PARSE_S, max_tries=1),
        arq_func(generate_atomic_notes, timeout=TIMEOUT_NOTES_S, max_tries=1),
        arq_func(extract_graph, timeout=TIMEOUT_GRAPH_S, max_tries=1),
        arq_func(run_chat_turn, timeout=TIMEOUT_CHAT_TURN_S, max_tries=1),
        arq_func(run_dreaming_job, timeout=TIMEOUT_DREAM_S, max_tries=1),
    ]
    # Global ceiling for any task that doesn't override (e.g. cron jobs).
    job_timeout = TIMEOUT_WORKER_DEFAULT_S
    # ``minute=None`` plus ``second=0`` is arq's canonical "once a minute"
    # config and prevents the catch-up burst we saw with ``set(range(60))``
    # where a freshly-started worker would re-fire the cron several times in
    # quick succession.
    cron_jobs = [cron(reconcile_stuck_documents, second=0)]
    on_startup = worker_startup
    on_shutdown = worker_shutdown
