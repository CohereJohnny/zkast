"""Redis hash + pub/sub helpers for generic jobs.

Sprint 5b adds:
- 7-day TTL on the job hash via EXPIRE NX on first write.
- A per-job Redis Stream (``zkast:jobs:<job_id>:log``) capped at 1000 entries
  so subscribers that arrive late can replay recent events.
- A ``record_log`` / ``record_metric`` helper that fans out to pub/sub +
  Stream + the durable ``ingestion_run_logs`` table.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

JOB_HASH_PREFIX = "zkast:job:"
JOB_CHANNEL_PREFIX = "zkast:jobs:"
JOB_STREAM_SUFFIX = ":log"

# Keep recent events available for replay when a UI subscriber arrives late.
JOB_STREAM_MAXLEN = 1000
# Job hashes and streams should not linger forever. They survive long enough
# to be useful for post-mortem; permanent history lives in ingestion_run_logs.
JOB_HASH_TTL_SECONDS = 7 * 24 * 3600

# Info logs matching these are mirrored to the activity theater as ``thought`` cards.
_THEATER_LOG_BLOCK = re.compile(
    r"worker started|^\s*\d+\s*%|Progress\s+\d|queued_",
    re.IGNORECASE,
)
_THEATER_LOG_EPISODE = re.compile(
    r"^episode\s+(\d+)\/(\d+):\s+\+(\d+)\s+entities,\s+\+(\d+)\s+edges",
    re.IGNORECASE,
)


def narrative_log_for_theater(message: str) -> str | None:
    """Return a theater-friendly label for a pipeline log line, or None to skip."""
    text = (message or "").strip()
    if len(text) < 6 or _THEATER_LOG_BLOCK.search(text):
        return None
    ep = _THEATER_LOG_EPISODE.match(text)
    if ep:
        idx, total, ents, edges = ep.groups()
        return f"Episode {idx}/{total} — mapped {ents} entities and {edges} edges"
    lower = text.lower()
    markers = (
        "parsed",
        "parsing",
        "synthesi",
        "extract",
        "created",
        "graph",
        "episode",
        "transcript",
        "chunk",
        "note",
        "entity",
        "relationship",
        "export",
        "index",
        "corpus",
        "community",
        "reading",
        "draft",
        "opening",
        "examining",
        "spotted",
        "wired",
        "outlined",
        "saved",
        "llm",
        "north",
    )
    if any(m in lower for m in markers):
        return text
    return None


def job_hash_key(job_id: str) -> str:
    return f"{JOB_HASH_PREFIX}{job_id}"


async def arq_queue_snapshot(redis: Any) -> dict[str, Any]:
    """Best-effort arq worker queue stats (arq 0.x Redis layout).

    - ``arq:queue`` is a ZSET of queued job ids (not a LIST).
    - In-flight jobs use keys ``arq:in-progress:{job_id}:{function}``.
    """
    queue_depth: int | None = None
    try:
        queue_depth = int(await redis.zcard("arq:queue"))
    except Exception:  # noqa: BLE001
        queue_depth = None

    in_progress: list[str] = []
    try:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match="arq:in-progress:*", count=200)
            for raw_key in keys:
                key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
                suffix = key.removeprefix("arq:in-progress:")
                if suffix.startswith("cron:"):
                    continue
                in_progress.append(suffix)
            if cursor == 0:
                break
    except Exception:  # noqa: BLE001
        in_progress = []

    return {"queue_depth": queue_depth, "in_progress": sorted(in_progress)}


def job_channel(job_id: str) -> str:
    return f"{JOB_CHANNEL_PREFIX}{job_id}"


def job_stream_key(job_id: str) -> str:
    return f"{JOB_CHANNEL_PREFIX}{job_id}{JOB_STREAM_SUFFIX}"


# arq ``in-progress`` suffixes: ``{job_id}:{function}`` for pipeline stages, or
# the full job id for GraphRAG/chat (``graphrag:{uuid}`` has colons — never
# ``rsplit(":", 1)`` those entries).
_ARQ_KNOWN_FUNCTION_SUFFIXES = (
    ":run_graphrag_index_job",
    ":generate_atomic_notes",
    ":extract_graph",
    ":parse_document",
    ":slack_import",
    ":parse",
    ":notes",
    ":graph",
)


def parse_arq_in_progress_suffix(entry: str) -> tuple[str, str | None]:
    """Parse an ``arq:in-progress:`` suffix into ``(job_id, function | None)``."""
    if not entry or entry.startswith("cron:"):
        return entry, None
    for suffix in _ARQ_KNOWN_FUNCTION_SUFFIXES:
        if entry.endswith(suffix):
            return entry[: -len(suffix)], suffix[1:]
    return entry, None


def _flatten_mapping(fields: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in fields.items():
        if val is None:
            continue
        if isinstance(val, (dict, list)):
            out[key] = json.dumps(val)
        else:
            out[key] = str(val)
    return out


async def job_hset(redis: Any, job_id: str, **fields: Any) -> None:
    """Set fields on the job hash and apply a 7-day NX TTL on first write."""
    key = job_hash_key(job_id)
    mapping = _flatten_mapping(fields)
    if not mapping:
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        has_created = await redis.hexists(key, "created_at")
        if not has_created:
            mapping.setdefault("created_at", now)
    except Exception:  # noqa: BLE001
        mapping.setdefault("created_at", now)
    mapping["updated_at"] = now
    await redis.hset(key, mapping=mapping)
    # nx=True only sets the TTL the first time the key is created; subsequent
    # hset writes don't reset it. Mirror on the stream too so both retire
    # together.
    try:
        await redis.expire(key, JOB_HASH_TTL_SECONDS, nx=True)
        await redis.expire(job_stream_key(job_id), JOB_HASH_TTL_SECONDS, nx=True)
    except TypeError:
        # Older redis-py builds don't support kwargs on expire; fall back.
        await redis.expire(key, JOB_HASH_TTL_SECONDS)
        await redis.expire(job_stream_key(job_id), JOB_HASH_TTL_SECONDS)


async def job_hgetall(redis: Any, job_id: str) -> dict[str, str]:
    raw = await redis.hgetall(job_hash_key(job_id))
    return dict(raw)


async def emit_activity(
    redis: Any,
    *,
    job_id: str,
    stage: str,
    label: str,
    detail: str | None = None,
    kind: str = "thought",
    data: dict[str, Any] | None = None,
) -> None:
    """Narrative telemetry for the pipeline activity theater (not the log view)."""
    await publish_job_event(
        redis,
        job_id,
        "activity",
        stage=stage,
        kind=kind,
        label=label,
        detail=detail,
        data=data or {},
    )


async def publish_job_event(redis: Any, job_id: str, event_type: str, **data: Any) -> None:
    """Publish a structured event to pub/sub and the per-job Redis Stream.

    Pub/sub keeps backward compatibility with the existing ``JobStreamBridge``.
    The Stream provides replay so a freshly-opened ``JobLogConsole`` shows
    recent history immediately. ``XADD MAXLEN ~ 1000`` keeps memory bounded.
    """
    payload: dict[str, Any] = {"type": event_type, **data}
    encoded = json.dumps(payload)
    await redis.publish(job_channel(job_id), encoded)
    try:
        await redis.xadd(
            job_stream_key(job_id),
            {"payload": encoded},
            maxlen=JOB_STREAM_MAXLEN,
            approximate=True,
        )
        await redis.expire(job_stream_key(job_id), JOB_HASH_TTL_SECONDS, nx=True)
    except TypeError:
        await redis.xadd(job_stream_key(job_id), {"payload": encoded}, maxlen=JOB_STREAM_MAXLEN)
    except Exception:  # noqa: BLE001
        # Streams should never fail the worker; pub/sub is the source of truth.
        pass


async def record_log(
    redis: Any,
    *,
    job_id: str,
    level: str,
    stage: str,
    message: str,
    data: dict[str, Any] | None = None,
    database_url: str | None = None,
    ingestion_run_id: str | None = None,
) -> None:
    """Emit a free-text log line + durably persist to ingestion_run_logs.

    ``level`` should be one of ``info`` / ``warning`` / ``error``.
    ``stage`` matches the pipeline stage name (``parsing``, ``generating_notes``,
    ``extracting_graph``, ``building_graph``).
    """
    payload: dict[str, Any] = {
        "type": "log",
        "level": level,
        "stage": stage,
        "message": message,
    }
    if data:
        payload["data"] = data
    encoded = json.dumps(payload)
    await redis.publish(job_channel(job_id), encoded)
    try:
        await redis.xadd(
            job_stream_key(job_id),
            {"payload": encoded},
            maxlen=JOB_STREAM_MAXLEN,
            approximate=True,
        )
        await redis.expire(job_stream_key(job_id), JOB_HASH_TTL_SECONDS, nx=True)
    except Exception:  # noqa: BLE001
        pass
    theater_label = narrative_log_for_theater(message) if level == "info" else None
    if theater_label:
        await emit_activity(
            redis,
            job_id=job_id,
            stage=stage,
            label=theater_label,
            kind="thought",
            data=data or {},
        )
    if database_url and ingestion_run_id:
        # Persist for post-mortem and the Diagnostics page. Imported lazily so
        # the job_redis module stays import-cheap.
        import asyncio

        from app.ingestion_logs_repo import insert_log_row

        try:
            await asyncio.to_thread(
                insert_log_row,
                database_url,
                ingestion_run_id=ingestion_run_id,
                level=level,
                stage=stage,
                message=message,
                data=data,
            )
        except Exception:  # noqa: BLE001
            # Durable logging is best-effort; never block the worker.
            pass


def decode_job_hash(raw: dict[str, str]) -> dict[str, Any]:
    """Normalize a Redis job hash for JSON APIs."""
    out: dict[str, Any] = dict(raw)
    prog = out.get("progress")
    if isinstance(prog, str):
        try:
            out["progress"] = json.loads(prog)
        except json.JSONDecodeError:
            pass
    return out


async def list_workspace_jobs(
    redis: Any,
    *,
    workspace_id: str,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """Return recent ``zkast:job:*`` hashes for one workspace (newest first)."""
    items: list[dict[str, Any]] = []
    cursor = 0
    scanned = 0
    max_scan = 3000
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match=f"{JOB_HASH_PREFIX}*", count=200)
        for k in keys:
            if isinstance(k, bytes):
                k = k.decode()
            scanned += 1
            if scanned > max_scan:
                break
            raw = await redis.hgetall(k)
            if not raw:
                continue
            if isinstance(raw, dict) and any(isinstance(v, bytes) for v in raw.values()):
                raw = {str(kk): (vv.decode() if isinstance(vv, bytes) else vv) for kk, vv in raw.items()}
            if raw.get("workspace_id") != workspace_id:
                continue
            job_id = k.removeprefix(JOB_HASH_PREFIX)
            row = decode_job_hash(raw)
            row["job_id"] = job_id
            items.append(row)
        if cursor == 0 or scanned > max_scan or len(items) >= limit * 3:
            break

    def _sort_key(row: dict[str, Any]) -> tuple[int, str]:
        status = str(row.get("status") or "").lower()
        active = status in ("running", "queued")
        ts = str(row.get("updated_at") or row.get("created_at") or "")
        return (0 if active else 1, ts)

    items.sort(key=lambda r: (_sort_key(r)[0], _sort_key(r)[1]), reverse=True)
    return items[:limit]


ARQ_FUNCTION_LABELS: dict[str, str] = {
    "parse": "Parsing",
    "notes": "Generating notes",
    "graph": "Extracting graph",
    "run_graphrag_index_job": "GraphRAG indexing",
}

STAGE_LABELS: dict[str, str] = {
    "queued": "Queued",
    "parsing": "Parsing",
    "generating_notes": "Generating notes",
    "extracting_graph": "Extracting graph",
    "building_graph": "Building graph",
    "complete": "Complete",
    "ready": "Ready",
    "wiki_generation": "Wiki generation",
    "dreaming": "Dreaming",
    "graphrag_indexing": "GraphRAG indexing",
}


def _parse_arq_in_progress(entries: list[str]) -> dict[str, str]:
    """Map pipeline job_id → arq function suffix (``parse`` / ``notes`` / ``graph``)."""
    out: dict[str, str] = {}
    for entry in entries:
        job_id, func = parse_arq_in_progress_suffix(entry)
        if job_id and func:
            out[job_id] = func
        elif job_id:
            out[job_id] = ""
    return out


def _iso_dt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def enrich_pipeline_jobs(
    database_url: str,
    jobs: list[dict[str, Any]],
    *,
    arq_in_progress: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Attach human labels, timestamps, and worker-active flags for the Jobs UI."""
    arq_active = _parse_arq_in_progress(arq_in_progress or [])
    if not jobs and not arq_active:
        return jobs
    doc_ids = list({str(j["document_id"]) for j in jobs if j.get("document_id")})
    run_ids = list({str(j["ingestion_run_id"]) for j in jobs if j.get("ingestion_run_id")})
    wiki_ids = list({str(j["wiki_space_id"]) for j in jobs if j.get("wiki_space_id")})
    agent_ids = list({str(j["agent_id"]) for j in jobs if j.get("agent_id")})

    docs: dict[str, dict[str, Any]] = {}
    runs: dict[str, dict[str, Any]] = {}
    wikis: dict[str, dict[str, Any]] = {}
    agents: dict[str, dict[str, Any]] = {}

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        if doc_ids:
            rows = conn.execute(
                """
                SELECT id::text AS id, original_filename, status
                FROM documents
                WHERE id = ANY(%s::uuid[])
                """,
                (doc_ids,),
            ).fetchall()
            docs = {str(r["id"]): dict(r) for r in rows}
        if run_ids:
            rows = conn.execute(
                """
                SELECT id::text AS id, started_at, ended_at, status
                FROM ingestion_runs
                WHERE id = ANY(%s::uuid[])
                """,
                (run_ids,),
            ).fetchall()
            runs = {str(r["id"]): dict(r) for r in rows}
        if wiki_ids:
            rows = conn.execute(
                """
                SELECT id::text AS id, name
                FROM wiki_spaces
                WHERE id = ANY(%s::uuid[])
                """,
                (wiki_ids,),
            ).fetchall()
            wikis = {str(r["id"]): dict(r) for r in rows}
        if agent_ids:
            rows = conn.execute(
                """
                SELECT id::text AS id, display_name, external_agent_id, provider
                FROM north_agents
                WHERE id = ANY(%s::uuid[])
                """,
                (agent_ids,),
            ).fetchall()
            agents = {str(r["id"]): dict(r) for r in rows}

    enriched: list[dict[str, Any]] = []
    for job in jobs:
        row = dict(job)
        jid = str(row.get("job_id") or "")
        doc = docs.get(str(row.get("document_id") or ""))
        run = runs.get(str(row.get("ingestion_run_id") or ""))
        wiki = wikis.get(str(row.get("wiki_space_id") or ""))
        agent = agents.get(str(row.get("agent_id") or ""))

        progress = row.get("progress")
        stage = ""
        percent: int | None = None
        progress_current: int | None = None
        progress_total: int | None = None
        progress_unit: str | None = None
        if isinstance(progress, dict):
            stage = str(progress.get("stage") or "")
            p = progress.get("percent")
            percent = int(p) if p is not None else None
            c = progress.get("current")
            t = progress.get("total")
            progress_current = int(c) if c is not None else None
            progress_total = int(t) if t is not None else None
            raw_unit = progress.get("unit")
            progress_unit = str(raw_unit) if raw_unit else None

        arq_func = arq_active.get(jid)
        worker_active = jid in arq_active
        row["worker_active"] = worker_active
        row["arq_function"] = arq_func
        if worker_active and arq_func and not stage:
            stage = {
                "parse": "parsing",
                "notes": "generating_notes",
                "graph": "building_graph",
                "run_graphrag_index_job": "graphrag_indexing",
            }.get(arq_func, stage)
        row["stage"] = stage
        row["percent"] = percent
        row["progress_current"] = progress_current
        row["progress_total"] = progress_total
        row["progress_unit"] = progress_unit or (
            "tokens" if stage == "generating_notes" and (progress_total or 0) >= 200 else "items"
        )
        if worker_active and percent is None and progress_total and progress_total > 0 and progress_current is not None:
            row["percent"] = min(99, int(100 * progress_current / progress_total))
        elif worker_active and percent is None:
            row["percent"] = {
                "parse": 10,
                "notes": 35,
                "graph": 55,
                "run_graphrag_index_job": 50,
            }.get(arq_func or "", 50)

        if doc:
            row["document_filename"] = doc.get("original_filename")
            row["document_status"] = doc.get("status")
        if run:
            row["ingestion_started_at"] = _iso_dt(run.get("started_at"))
            row["ingestion_ended_at"] = _iso_dt(run.get("ended_at"))
        if wiki:
            row["wiki_space_name"] = wiki.get("name")

        submitted = row.get("created_at") or row.get("ingestion_started_at")
        row["submitted_at"] = submitted

        if doc and doc.get("original_filename"):
            title = str(doc["original_filename"])
        elif wiki and wiki.get("name"):
            title = f"Wiki: {wiki['name']}"
        elif row.get("title"):
            title = str(row["title"])
        elif str(row.get("kind") or "") == "graphrag_index":
            if agent:
                name = (
                    agent.get("display_name") or agent.get("external_agent_id") or row.get("agent_id")
                )
                if agent.get("provider") == "slack":
                    title = f"GraphRAG: #{name}"
                else:
                    title = f"GraphRAG: {name}"
            else:
                title = "GraphRAG: whole workspace"
        else:
            title = str(row.get("kind") or "Pipeline job").replace("_", " ")

        stage_label = STAGE_LABELS.get(stage) or STAGE_LABELS.get(arq_func or "", "")
        if not stage_label and arq_func:
            stage_label = ARQ_FUNCTION_LABELS.get(arq_func, arq_func)
        row["title"] = title
        row["stage_label"] = stage_label or "—"
        enriched.append(row)

    def _sort_key(r: dict[str, Any]) -> tuple[int, str]:
        active = (
            r.get("worker_active")
            or str(r.get("status") or "").lower() in ("running", "queued")
        )
        ts = str(r.get("updated_at") or r.get("submitted_at") or "")
        return (0 if active else 1, ts)

    enriched.sort(
        key=lambda r: (_sort_key(r)[0], _sort_key(r)[1]),
        reverse=True,
    )
    return enriched


async def record_metric(
    redis: Any,
    *,
    job_id: str,
    name: str,
    value: float | int,
    stage: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Emit a metric (e.g. ``entity_count``, ``tokens_consumed``).

    Metrics are intentionally NOT persisted to ``ingestion_run_logs`` to keep
    that table cheap. Use ``record_log`` for anything worth post-mortem.
    """
    payload: dict[str, Any] = {
        "type": "metric",
        "name": name,
        "value": value,
        "stage": stage,
    }
    if data:
        payload["data"] = data
    encoded = json.dumps(payload)
    await redis.publish(job_channel(job_id), encoded)
    try:
        await redis.xadd(
            job_stream_key(job_id),
            {"payload": encoded},
            maxlen=JOB_STREAM_MAXLEN,
            approximate=True,
        )
        await redis.expire(job_stream_key(job_id), JOB_HASH_TTL_SECONDS, nx=True)
    except Exception:  # noqa: BLE001
        pass
