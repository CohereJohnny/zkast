"""Sprint 6 — refusal short-circuit (FR-45).

When ``chat_turn._retrieve`` returns zero documents, the task must:

1. Persist the ``RetrievalRecord`` row (empty payload).
2. Skip the Cohere call entirely (no ``chat_stream_grounded`` invocation).
3. Mark the assistant message ``status='refused'``.
4. Emit ``message_complete`` with ``finish_reason='refused'`` and a
   final ``job_completed`` event (not ``job_failed``).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app import chat_turn


_FAKE_SETTINGS = SimpleNamespace(
    database_url="postgresql://stub/none",
    redis_url="redis://stub:6379",
    falkordb_host="stub",
    internal_pipeline_token="stub",
    master_encryption_key="stub",
    large_model="command-a-plus-05-2026",
)


def _ctx() -> dict[str, Any]:
    redis = AsyncMock()
    redis.set = AsyncMock()
    return {"redis": redis, "database_url": "postgresql://stub/none"}


def _patch_common(monkeypatch: pytest.MonkeyPatch, *, retrieve_returns: tuple) -> dict[str, Any]:
    """Wire up the cross-module mocks every chat_turn test needs."""
    captured: dict[str, Any] = {
        "events": [],
        "updates": [],
        "retrieval": None,
        "citations": [],
        "chat_calls": 0,
    }

    async def fake_publish(_redis, _job_id, event_type, **kwargs):
        captured["events"].append({"type": event_type, **kwargs})

    async def fake_record_log(_redis, **kwargs):
        captured["events"].append({"type": "log", **kwargs})

    async def fake_record_metric(_redis, **kwargs):
        captured["events"].append({"type": "metric", **kwargs})

    async def fake_job_hset(_redis, _job_id, **kwargs):
        captured["events"].append({"type": "job_hset", **kwargs})

    monkeypatch.setattr(chat_turn, "publish_job_event", fake_publish)
    monkeypatch.setattr(chat_turn, "record_log", fake_record_log)
    monkeypatch.setattr(chat_turn, "record_metric", fake_record_metric)
    monkeypatch.setattr(chat_turn, "job_hset", fake_job_hset)
    monkeypatch.setattr(chat_turn, "get_settings", lambda: _FAKE_SETTINGS)

    monkeypatch.setattr(
        chat_turn,
        "fetch_session",
        lambda *_a, **kw: {
            "id": kw["session_id"],
            "workspace_id": kw["workspace_id"],
            "title": "test",
            "scope": {},
            "model_settings": {},
        },
    )
    monkeypatch.setattr(
        chat_turn,
        "fetch_message",
        lambda *_a, **kw: {
            "id": kw["message_id"],
            "role": "user",
            "content": "what is the workspace about?",
            "status": "complete",
        },
    )
    monkeypatch.setattr(chat_turn, "list_messages_for_session", lambda *_a, **_k: [])
    monkeypatch.setattr(chat_turn, "resolve_cohere_api_key", lambda *_a, **_k: "test-key")
    monkeypatch.setattr(chat_turn, "fetch_pipeline_settings", lambda *_a, **_k: {})

    def fake_update(_db, **kwargs):
        captured["updates"].append(kwargs)

    def fake_insert_retrieval(_db, **kwargs):
        captured["retrieval"] = kwargs
        return "rr-fake-uuid"

    def fake_insert_citations(_db, **kwargs):
        captured["citations"].append(kwargs)
        return len(kwargs.get("rows") or [])

    def fake_patch_session(_db, **_kw):
        return None

    monkeypatch.setattr(chat_turn, "update_assistant_message", fake_update)
    monkeypatch.setattr(chat_turn, "insert_retrieval_record", fake_insert_retrieval)
    monkeypatch.setattr(chat_turn, "insert_citation_rows", fake_insert_citations)
    monkeypatch.setattr(chat_turn, "patch_session", fake_patch_session)

    async def fake_retrieve(*_a, **_k):
        return retrieve_returns

    monkeypatch.setattr(chat_turn, "_retrieve", fake_retrieve)

    async def fake_chat_stream_grounded(**_kwargs):
        captured["chat_calls"] += 1
        # If a refusal test calls this, the assertion will catch it.
        raise AssertionError(
            "chat_stream_grounded must not be called in the refusal path"
        )

    monkeypatch.setattr(chat_turn, "chat_stream_grounded", fake_chat_stream_grounded)

    return captured


def test_refusal_skips_cohere_and_marks_message_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_common(
        monkeypatch,
        retrieve_returns=([], [], 0, False, "graph_graphiti_context_v1"),
    )

    asyncio.run(
        chat_turn.run_chat_turn(
            _ctx(),
            workspace_id="ws-1",
            session_id="ses-1",
            user_message_id="user-1",
            assistant_message_id="asst-1",
            turn_id="turn-1",
        )
    )

    # No Cohere call.
    assert captured["chat_calls"] == 0

    # RetrievalRecord persisted before any LLM activity.
    assert captured["retrieval"] is not None
    assert captured["retrieval"]["message_id"] == "asst-1"
    assert captured["retrieval"]["total_candidates"] == 0
    assert captured["retrieval"]["retrieved_items"] == []

    # Assistant message ended up `refused`.
    refused_updates = [u for u in captured["updates"] if u.get("status") == "refused"]
    assert refused_updates, "Expected a `refused` status update on the assistant message"
    assert refused_updates[0]["message_id"] == "asst-1"
    assert refused_updates[0].get("completed_now") is True

    # Final event sequence includes message_complete(refused) and job_completed.
    types = [e.get("type") for e in captured["events"]]
    assert "message_complete" in types
    msg_complete = next(e for e in captured["events"] if e.get("type") == "message_complete")
    assert msg_complete["finish_reason"] == "refused"
    assert "job_completed" in types
    assert "job_failed" not in types
