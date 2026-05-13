"""SSE subscription for job channels.

Sprint 5b: the SSE generator now replays recent events from the per-job
Redis Stream (``zkast:jobs:<id>:log``) before tailing the live pub/sub
channel. New subscribers see the last 200 events immediately instead of an
empty drawer until the next emit.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from app.job_redis import job_channel, job_stream_key

REPLAY_LIMIT = 200


def _sse_format(payload: str) -> str:
    return f"data: {payload}\n\n"


async def _replay_from_stream(redis: Any, job_id: str) -> AsyncIterator[str]:
    """Yield recent payloads from the per-job Stream before live tailing."""
    stream = job_stream_key(job_id)
    try:
        # XRANGE returns entries oldest -> newest.
        entries = await redis.xrange(stream, count=REPLAY_LIMIT)
    except Exception:  # noqa: BLE001
        return
    for entry in entries or []:
        try:
            _entry_id, fields = entry
            payload = fields.get("payload") if isinstance(fields, dict) else None
            if payload is None and isinstance(fields, list):
                # redis-py occasionally returns flat [key, value] lists.
                for k, v in zip(fields[0::2], fields[1::2]):
                    if k == "payload":
                        payload = v
                        break
            if isinstance(payload, bytes):
                payload = payload.decode()
            if payload:
                yield _sse_format(payload)
        except Exception:  # noqa: BLE001
            continue


async def sse_job_events(redis: Any, job_id: str) -> AsyncIterator[str]:
    """SSE generator: replay last N events, then tail pub/sub for live ones.

    The two-phase design keeps the wire format unchanged for existing
    consumers (``JobStreamBridge``) while making the new ``JobLogConsole``
    drawer feel instant.
    """
    # Phase 1 — replay recent history.
    async for chunk in _replay_from_stream(redis, job_id):
        yield chunk

    # Phase 2 — live tail.
    pubsub = redis.pubsub()
    await pubsub.subscribe(job_channel(job_id))
    try:
        # Send a comment line every 15s so proxies don't drop the
        # connection during quiet stages. Comment lines (": ...") are
        # ignored by EventSource consumers.
        last_keepalive = asyncio.get_event_loop().time()
        async for msg in pubsub.listen():
            now = asyncio.get_event_loop().time()
            if now - last_keepalive > 15:
                yield ": keepalive\n\n"
                last_keepalive = now
            if msg["type"] != "message":
                continue
            data = msg["data"]
            if isinstance(data, bytes):
                data = data.decode()
            yield _sse_format(data)
            last_keepalive = now
    finally:
        await pubsub.unsubscribe(job_channel(job_id))
        await pubsub.aclose()
