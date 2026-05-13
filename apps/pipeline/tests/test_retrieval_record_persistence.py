"""Sprint 6 — FR-41: ``RetrievalRecord`` is persisted *before* the LLM call.

Pins the call order so a future refactor that moves the
``insert_retrieval_record`` step after ``chat_stream_grounded`` (e.g. for
"performance") breaks loudly. The invariant exists so we always have a
post-mortem record of what context grounded a given assistant message,
even if the Cohere call fails or is cancelled.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app import chat_turn
from app.cohere_chat import ChatDocument, ChatStreamResult


_FAKE_SETTINGS = SimpleNamespace(
    database_url="postgresql://stub/none",
    redis_url="redis://stub:6379",
    falkordb_host="stub",
    internal_pipeline_token="stub",
    master_encryption_key="stub",
    large_model="command-a-plus-05-2026",
)


def _ctx() -> dict[str, Any]:
    return {"redis": AsyncMock(), "database_url": "postgresql://stub/none"}


def test_retrieval_record_persisted_before_first_cohere_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_order: list[str] = []

    async def fake_event(*_a, **_k):
        return None

    async def fake_noop(*_a, **_k):
        return None

    monkeypatch.setattr(chat_turn, "publish_job_event", fake_event)
    monkeypatch.setattr(chat_turn, "record_log", fake_noop)
    monkeypatch.setattr(chat_turn, "record_metric", fake_noop)
    monkeypatch.setattr(chat_turn, "job_hset", fake_noop)
    monkeypatch.setattr(chat_turn, "get_settings", lambda: _FAKE_SETTINGS)
    monkeypatch.setattr(
        chat_turn,
        "fetch_session",
        lambda *_a, **kw: {
            "id": kw["session_id"],
            "workspace_id": kw["workspace_id"],
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
            "content": "x",
            "status": "complete",
        },
    )
    monkeypatch.setattr(chat_turn, "list_messages_for_session", lambda *_a, **_k: [])
    monkeypatch.setattr(chat_turn, "resolve_cohere_api_key", lambda *_a, **_k: "test-key")
    monkeypatch.setattr(chat_turn, "fetch_pipeline_settings", lambda *_a, **_k: {})
    monkeypatch.setattr(chat_turn, "patch_session", lambda *_a, **_k: None)
    monkeypatch.setattr(chat_turn, "update_assistant_message", lambda *_a, **_k: None)
    monkeypatch.setattr(chat_turn, "insert_citation_rows", lambda *_a, **_k: 0)

    def fake_insert_retrieval(*_a, **_k):
        call_order.append("insert_retrieval_record")
        return "rr-1"

    monkeypatch.setattr(chat_turn, "insert_retrieval_record", fake_insert_retrieval)

    async def fake_retrieve(*_a, **_k):
        docs = [ChatDocument(id="note:1", text="x")]
        return (
            [{"kind": "note", "id": "1", "excerpt": "x"}],
            docs,
            1,
            False,
            "graph_graphiti_context_v1",
        )

    monkeypatch.setattr(chat_turn, "_retrieve", fake_retrieve)

    async def fake_chat_stream_grounded(**_kwargs):
        call_order.append("chat_stream_grounded")
        return ChatStreamResult(
            text="ok",
            citations=[],
            finish_reason="COMPLETE",
            tokens_in=1,
            tokens_out=1,
            used_streaming=True,
        )

    monkeypatch.setattr(chat_turn, "chat_stream_grounded", fake_chat_stream_grounded)

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

    assert call_order == ["insert_retrieval_record", "chat_stream_grounded"], (
        f"FR-41 invariant violated. Saw: {call_order}"
    )


def test_retrieval_record_persisted_even_when_chat_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cohere failure must NOT skip the RetrievalRecord write — by the
    time we throw, the row is already there."""
    persisted: list[str] = []

    async def fake_event(*_a, **_k):
        return None

    async def fake_noop(*_a, **_k):
        return None

    monkeypatch.setattr(chat_turn, "publish_job_event", fake_event)
    monkeypatch.setattr(chat_turn, "record_log", fake_noop)
    monkeypatch.setattr(chat_turn, "record_metric", fake_noop)
    monkeypatch.setattr(chat_turn, "job_hset", fake_noop)
    monkeypatch.setattr(chat_turn, "get_settings", lambda: _FAKE_SETTINGS)
    monkeypatch.setattr(
        chat_turn,
        "fetch_session",
        lambda *_a, **kw: {
            "id": kw["session_id"],
            "workspace_id": kw["workspace_id"],
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
            "content": "x",
            "status": "complete",
        },
    )
    monkeypatch.setattr(chat_turn, "list_messages_for_session", lambda *_a, **_k: [])
    monkeypatch.setattr(chat_turn, "resolve_cohere_api_key", lambda *_a, **_k: "test-key")
    monkeypatch.setattr(chat_turn, "fetch_pipeline_settings", lambda *_a, **_k: {})
    monkeypatch.setattr(chat_turn, "patch_session", lambda *_a, **_k: None)
    monkeypatch.setattr(chat_turn, "update_assistant_message", lambda *_a, **_k: None)
    monkeypatch.setattr(chat_turn, "insert_citation_rows", lambda *_a, **_k: 0)

    def fake_insert_retrieval(*_a, **_k):
        persisted.append("rr-1")
        return "rr-1"

    monkeypatch.setattr(chat_turn, "insert_retrieval_record", fake_insert_retrieval)

    async def fake_retrieve(*_a, **_k):
        return (
            [{"kind": "note", "id": "1", "excerpt": "x"}],
            [ChatDocument(id="note:1", text="x")],
            1,
            False,
            "graph_graphiti_context_v1",
        )

    monkeypatch.setattr(chat_turn, "_retrieve", fake_retrieve)

    async def fake_chat_stream_grounded(**_kwargs):
        raise RuntimeError("cohere is having a moment")

    monkeypatch.setattr(chat_turn, "chat_stream_grounded", fake_chat_stream_grounded)

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

    assert persisted == ["rr-1"], (
        "Retrieval record must still be persisted even when Cohere fails"
    )
