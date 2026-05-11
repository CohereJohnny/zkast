"""SSE subscription for job channels."""

from __future__ import annotations

from typing import AsyncIterator

from app.job_redis import job_channel


async def sse_job_events(redis: object, job_id: str) -> AsyncIterator[str]:
    pubsub = redis.pubsub()  # type: ignore[assignment]
    await pubsub.subscribe(job_channel(job_id))
    try:
        async for msg in pubsub.listen():  # type: ignore[attr-defined]
            if msg["type"] != "message":
                continue
            data = msg["data"]
            if isinstance(data, bytes):
                data = data.decode()
            yield f"data: {data}\n\n"
    finally:
        await pubsub.unsubscribe(job_channel(job_id))
        await pubsub.aclose()
