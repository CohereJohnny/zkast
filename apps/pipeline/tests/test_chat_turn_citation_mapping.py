"""Sprint 6 — citation mapping.

Cohere's citation events carry ``source_ids`` like ``"note:<uuid>"`` /
``"entity:<uuid>"`` (the prefix scheme we control in ``_retrieve``).
``chat_turn`` must:

1. Persist a ``chat_citations`` row per citation, with the correct
   ``text_start``/``text_end`` and ``sources[]`` array.
2. Decode the prefix into the right ``kind`` so the web hover card
   knows whether to link to a note, entity, relationship, or page.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app import chat_turn
from app.cohere_chat import ChatDocument, ChatStreamResult, CitationSpan


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
    return {"redis": redis, "database_url": "postgresql://stub/none"}


def test_citation_rows_persisted_with_correct_kind_and_offsets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {
        "events": [],
        "updates": [],
        "citations": [],
        "chat_call_kwargs": None,
    }

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
            "content": "tell me about ada lovelace",
            "status": "complete",
        },
    )
    monkeypatch.setattr(chat_turn, "list_messages_for_session", lambda *_a, **_k: [])
    monkeypatch.setattr(chat_turn, "resolve_cohere_api_key", lambda *_a, **_k: "test-key")
    monkeypatch.setattr(chat_turn, "fetch_pipeline_settings", lambda *_a, **_k: {})
    monkeypatch.setattr(chat_turn, "patch_session", lambda *_a, **_k: None)
    monkeypatch.setattr(chat_turn, "insert_retrieval_record", lambda *_a, **_k: "rr-1")

    def fake_update(_db, **kw):
        captured["updates"].append(kw)

    monkeypatch.setattr(chat_turn, "update_assistant_message", fake_update)

    def fake_insert_citations(_db, *, message_id, rows):
        captured["citations"].append({"message_id": message_id, "rows": list(rows)})
        return len(rows)

    monkeypatch.setattr(chat_turn, "insert_citation_rows", fake_insert_citations)

    # Retrieval returns two documents whose ids carry the prefix scheme.
    docs = [
        ChatDocument(id="note:note-aaa", text="Ada Lovelace wrote algorithms.", title="Concept"),
        ChatDocument(id="entity:ent-bbb", text="Ada Lovelace.", title="Person"),
    ]
    retrieved_items = [
        {"kind": "note", "id": "note-aaa", "excerpt": "Ada Lovelace wrote algorithms."},
        {"kind": "entity", "id": "ent-bbb", "excerpt": "Ada Lovelace."},
    ]

    async def fake_retrieve(*_a, **_k):
        return retrieved_items, docs, 2, False, "graph_graphiti_context_v1"

    monkeypatch.setattr(chat_turn, "_retrieve", fake_retrieve)

    # Mock chat_stream_grounded so it returns a ChatStreamResult with two
    # citations *and* fires the callbacks the way the real wrapper does
    # for streaming responses.
    async def fake_chat_stream_grounded(**kwargs):
        captured["chat_call_kwargs"] = kwargs
        on_token = kwargs["on_token"]
        on_citation = kwargs["on_citation"]
        await on_token("Ada Lovelace ")
        await on_token("wrote algorithms.")
        await on_citation(
            CitationSpan(
                text_start=0,
                text_end=12,
                text="Ada Lovelace",
                source_ids=["note:note-aaa"],
            )
        )
        await on_citation(
            CitationSpan(
                text_start=13,
                text_end=29,
                text="wrote algorithms",
                source_ids=["entity:ent-bbb"],
            )
        )
        return ChatStreamResult(
            text="Ada Lovelace wrote algorithms.",
            citations=[],  # citations already fired via callback (streaming path)
            finish_reason="COMPLETE",
            tokens_in=4,
            tokens_out=7,
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

    # Cohere was called once with our prefixed documents.
    assert captured["chat_call_kwargs"] is not None
    assert [d.id for d in captured["chat_call_kwargs"]["documents"]] == [
        "note:note-aaa",
        "entity:ent-bbb",
    ]

    # Exactly one insert_citation_rows call with two rows, both keyed to asst-1.
    assert len(captured["citations"]) == 1
    insert = captured["citations"][0]
    assert insert["message_id"] == "asst-1"
    rows = insert["rows"]
    assert len(rows) == 2

    # Row 0: text_start=0, text_end=12, sources -> note
    assert rows[0]["text_start"] == 0
    assert rows[0]["text_end"] == 12
    src0 = rows[0]["sources"]
    assert len(src0) == 1
    assert src0[0]["kind"] == "note"
    assert src0[0]["id"] == "note-aaa"

    # Row 1: text_end=29, sources -> entity
    assert rows[1]["text_start"] == 13
    assert rows[1]["text_end"] == 29
    src1 = rows[1]["sources"]
    assert src1[0]["kind"] == "entity"
    assert src1[0]["id"] == "ent-bbb"

    # Final assistant-message update is `complete` with tokens populated.
    complete_updates = [u for u in captured["updates"] if u.get("status") == "complete"]
    assert complete_updates and complete_updates[-1]["tokens_in"] == 4
    assert complete_updates[-1]["tokens_out"] == 7

    # And the SSE event stream surfaced a citation event per row.
    citation_events = [e for e in captured["events"] if e.get("type") == "citation"]
    assert len(citation_events) == 2
