"""Redis hash + pub/sub helpers for generic jobs."""

from __future__ import annotations

import json
from typing import Any

JOB_HASH_PREFIX = "zkast:job:"
JOB_CHANNEL_PREFIX = "zkast:jobs:"


def job_hash_key(job_id: str) -> str:
    return f"{JOB_HASH_PREFIX}{job_id}"


def job_channel(job_id: str) -> str:
    return f"{JOB_CHANNEL_PREFIX}{job_id}"


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
    key = job_hash_key(job_id)
    mapping = _flatten_mapping(fields)
    if mapping:
        await redis.hset(key, mapping=mapping)


async def job_hgetall(redis: Any, job_id: str) -> dict[str, str]:
    raw = await redis.hgetall(job_hash_key(job_id))
    return dict(raw)


async def publish_job_event(redis: Any, job_id: str, event_type: str, **data: Any) -> None:
    payload = {"type": event_type, **data}
    await redis.publish(job_channel(job_id), json.dumps(payload))
