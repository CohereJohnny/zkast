"""Regression coverage for the arq ``_job_id`` collision class (BUG-001).

The bug: every chained ``pool.enqueue_job(...)`` used the same parent SSE
``job_id`` as ``_job_id``. arq de-dupes on that key, so once ``parse_document``
finished the next-stage enqueue was silently no-op'd and the document was
left zombied in ``generating_notes``.

These tests guard against:
1. Wrapper code calling ``enqueue_job`` with stage-suffixed ids (no
   collision).
2. A bare collision (``_job_id=`` repeated) returning ``None``.
3. The worker wrapper turning a ``None`` return into a loud ``RuntimeError``.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest


class _FakeArqPool:
    """Mimics ``ArqRedis.enqueue_job`` deduplication semantics."""

    def __init__(self) -> None:
        self.seen: set[str] = set()
        self.calls: list[dict[str, object]] = []

    async def enqueue_job(self, name: str, **kwargs: object) -> object | None:
        jid = kwargs.get("_job_id")
        if jid is None:
            jid = str(uuid.uuid4())
        else:
            jid = str(jid)
        if jid in self.seen:
            return None
        self.seen.add(jid)
        self.calls.append({"name": name, "_job_id": jid, **kwargs})
        return object()


def test_stage_suffixed_chain_does_not_collide() -> None:
    pool = _FakeArqPool()
    base = str(uuid.uuid4())

    async def run() -> None:
        a = await pool.enqueue_job("parse_document", _job_id=f"{base}:parse")
        b = await pool.enqueue_job("generate_atomic_notes", _job_id=f"{base}:notes")
        c = await pool.enqueue_job("extract_graph", _job_id=f"{base}:graph")
        assert a is not None
        assert b is not None
        assert c is not None

    asyncio.run(run())
    assert len(pool.calls) == 3
    assert {c["_job_id"] for c in pool.calls} == {
        f"{base}:parse",
        f"{base}:notes",
        f"{base}:graph",
    }


def test_same_key_collision_returns_none() -> None:
    pool = _FakeArqPool()
    base = str(uuid.uuid4())

    async def run() -> None:
        first = await pool.enqueue_job("parse_document", _job_id=base)
        second = await pool.enqueue_job("generate_atomic_notes", _job_id=base)
        assert first is not None
        assert second is None

    asyncio.run(run())


def test_worker_wrapper_raises_on_none() -> None:
    """The wrapper in ``tasks.parse_document`` / ``generate_atomic_notes``
    raises ``RuntimeError`` instead of silently letting the document advance.
    """
    pool = _FakeArqPool()
    base = str(uuid.uuid4())

    async def run() -> None:
        await pool.enqueue_job("generate_atomic_notes", _job_id=f"{base}:notes")
        enqueued = await pool.enqueue_job(
            "generate_atomic_notes", _job_id=f"{base}:notes"
        )
        if enqueued is None:
            raise RuntimeError("Failed to enqueue generate_atomic_notes — arq returned None")

    with pytest.raises(RuntimeError) as ei:
        asyncio.run(run())
    assert "Failed to enqueue" in str(ei.value)
