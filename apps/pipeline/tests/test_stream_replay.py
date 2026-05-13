"""A2 — SSE event stream replay before tailing pub/sub.

We exercise the helper directly with a stub redis double; no live Redis
needed. Confirms the wire format is ``data: <json>\\n\\n`` for replayed
entries.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import pytest

from app.jobs_stream import _replay_from_stream


class _StubRedis:
    def __init__(self, stream: list[tuple[str, dict[str, Any]]]) -> None:
        self._stream = stream

    async def xrange(self, _key: str, count: int = 200) -> list[tuple[str, dict[str, Any]]]:
        return self._stream[:count]


async def _collect(agen: AsyncIterator[str]) -> list[str]:
    out: list[str] = []
    async for chunk in agen:
        out.append(chunk)
    return out


def test_replay_from_stream_emits_sse_lines() -> None:
    payload_a = json.dumps({"type": "log", "level": "info", "message": "step 1"})
    payload_b = json.dumps({"type": "metric", "name": "entity_count", "value": 12})
    redis = _StubRedis(
        [
            ("0-1", {"payload": payload_a}),
            ("0-2", {"payload": payload_b}),
        ]
    )

    out = asyncio.run(_collect(_replay_from_stream(redis, "job-1")))
    assert out == [f"data: {payload_a}\n\n", f"data: {payload_b}\n\n"]


def test_replay_from_stream_handles_empty() -> None:
    out = asyncio.run(_collect(_replay_from_stream(_StubRedis([]), "job-2")))
    assert out == []


def test_replay_from_stream_tolerates_missing_payload() -> None:
    redis = _StubRedis([("0-1", {"unrelated": "value"})])
    out = asyncio.run(_collect(_replay_from_stream(redis, "job-3")))
    assert out == []
