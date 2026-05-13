"""Sprint 6 — cancellation path.

If ``asyncio.CancelledError`` is raised inside the Cohere call (arq
job timeout or worker shutdown), ``chat_turn`` must:

1. Set the assistant message ``status='cancelled'``.
2. Emit a ``job_cancelled`` SSE event.
3. Re-raise ``CancelledError`` (arq needs the signal to mark the job).

Also pins the ``_classify_cancel_reason`` import path so a future refactor
that moves the helper out of ``app.tasks`` breaks loudly.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app import chat_turn
from app.cohere_chat import ChatDocument


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


def test_cancelled_error_marks_message_cancelled_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {"events": [], "updates": []}

    async def fake_event(_r, _id, event_type, **kw):
        captured["events"].append({"type": event_type, **kw})

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
            "content": "tell me about anything",
            "status": "complete",
        },
    )
    monkeypatch.setattr(chat_turn, "list_messages_for_session", lambda *_a, **_k: [])
    monkeypatch.setattr(chat_turn, "resolve_cohere_api_key", lambda *_a, **_k: "test-key")
    monkeypatch.setattr(chat_turn, "fetch_pipeline_settings", lambda *_a, **_k: {})
    monkeypatch.setattr(chat_turn, "patch_session", lambda *_a, **_k: None)
    monkeypatch.setattr(chat_turn, "insert_retrieval_record", lambda *_a, **_k: "rr-1")
    monkeypatch.setattr(chat_turn, "insert_citation_rows", lambda *_a, **_k: 0)

    def fake_update(_db, **kw):
        captured["updates"].append(kw)

    monkeypatch.setattr(chat_turn, "update_assistant_message", fake_update)

    async def fake_retrieve(*_a, **_k):
        docs = [ChatDocument(id="note:foo", text="hello")]
        return [{"kind": "note", "id": "foo", "excerpt": "hello"}], docs, 1, False

    monkeypatch.setattr(chat_turn, "_retrieve", fake_retrieve)

    async def fake_chat_stream_grounded(**_kwargs):
        # Mimic an arq job-timeout hitting mid-stream.
        raise asyncio.CancelledError()

    monkeypatch.setattr(chat_turn, "chat_stream_grounded", fake_chat_stream_grounded)

    with pytest.raises(asyncio.CancelledError):
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

    # Assistant message ended up cancelled with a non-empty failure_reason.
    cancelled_updates = [u for u in captured["updates"] if u.get("status") == "cancelled"]
    assert cancelled_updates, "Expected a cancelled status update"
    assert cancelled_updates[0]["message_id"] == "asst-1"
    assert cancelled_updates[0].get("failure_reason"), (
        "failure_reason must be populated (BUG-008 — empty failure_reason)"
    )

    # job_cancelled SSE event fired.
    types = [e.get("type") for e in captured["events"]]
    assert "job_cancelled" in types
    # And we *did not* emit job_completed — the cancellation aborts the
    # success path.
    assert "job_completed" not in types


def test_classify_cancel_reason_is_importable_for_chat_turn() -> None:
    """Pin the imports so a refactor that moves the helper away from
    ``app.tasks`` breaks here, not in production."""
    from app.tasks import _classify_cancel_reason  # noqa: F401
