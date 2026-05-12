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
from typing import Any

JOB_HASH_PREFIX = "zkast:job:"
JOB_CHANNEL_PREFIX = "zkast:jobs:"
JOB_STREAM_SUFFIX = ":log"

# Keep recent events available for replay when a UI subscriber arrives late.
JOB_STREAM_MAXLEN = 1000
# Job hashes and streams should not linger forever. They survive long enough
# to be useful for post-mortem; permanent history lives in ingestion_run_logs.
JOB_HASH_TTL_SECONDS = 7 * 24 * 3600


def job_hash_key(job_id: str) -> str:
    return f"{JOB_HASH_PREFIX}{job_id}"


def job_channel(job_id: str) -> str:
    return f"{JOB_CHANNEL_PREFIX}{job_id}"


def job_stream_key(job_id: str) -> str:
    return f"{JOB_CHANNEL_PREFIX}{job_id}{JOB_STREAM_SUFFIX}"


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
