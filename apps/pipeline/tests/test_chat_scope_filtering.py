"""Sprint 6 — scope filters apply to retrieval and persist on the message.

When a session ``scope`` carries ``entity_types`` / ``edge_types`` /
``pinned_snapshot_id`` etc., ``chat_turn`` must:

1. Pass those filters down into ``_retrieve`` so Graphiti's search and
   the Postgres-side post-filter both see them.
2. Persist the effective scope on the assistant message
   (``effective_scope_snapshot`` on insert) so audit-style replays know
   exactly what the LLM saw.

The retrieval code path is heavily branching (Graphiti + Postgres); we
isolate it from those deps and verify (a) the scope object flows in and
(b) the persistence layer carries the scope to the right column.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
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


def test_str_list_normalizes_csv_and_arrays() -> None:
    """The internal helper must normalize None, CSV, and arrays into a
    list of trimmed strings — the public scope-picker can send either
    format from the UI."""
    assert chat_turn._str_list(None) == []
    assert chat_turn._str_list("") == []
    assert chat_turn._str_list("Person, Organization") == ["Person", "Organization"]
    assert chat_turn._str_list(["Person", " Organization "]) == [
        "Person",
        "Organization",
    ]


def test_session_scope_passes_into_retrieve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The active session's ``scope`` JSON must reach ``_retrieve`` unchanged
    so it can apply entity_types / edge_types / tag / document filters."""
    captured: dict[str, Any] = {"retrieve_kwargs": None}

    async def fake_event(*_a, **_k):
        return None

    async def fake_noop(*_a, **_k):
        return None

    monkeypatch.setattr(chat_turn, "publish_job_event", fake_event)
    monkeypatch.setattr(chat_turn, "record_log", fake_noop)
    monkeypatch.setattr(chat_turn, "record_metric", fake_noop)
    monkeypatch.setattr(chat_turn, "job_hset", fake_noop)
    monkeypatch.setattr(chat_turn, "get_settings", lambda: _FAKE_SETTINGS)

    scope = {
        "entity_types": ["Person"],
        "edge_types": ["WORKS_FOR"],
        "tags": ["safety"],
        "document_ids": ["00000000-0000-4000-8000-000000000001"],
        "seed_entity_ids": ["00000000-0000-4000-8000-000000000002"],
        "valid_at": "2024-01-15T00:00:00+00:00",
    }
    monkeypatch.setattr(
        chat_turn,
        "fetch_session",
        lambda *_a, **kw: {
            "id": kw["session_id"],
            "workspace_id": kw["workspace_id"],
            "scope": scope,
            "model_settings": {},
        },
    )
    monkeypatch.setattr(
        chat_turn,
        "fetch_message",
        lambda *_a, **kw: {
            "id": kw["message_id"],
            "role": "user",
            "content": "ask",
            "status": "complete",
        },
    )
    monkeypatch.setattr(chat_turn, "list_messages_for_session", lambda *_a, **_k: [])
    monkeypatch.setattr(chat_turn, "resolve_cohere_api_key", lambda *_a, **_k: "key")
    monkeypatch.setattr(chat_turn, "fetch_pipeline_settings", lambda *_a, **_k: {})
    monkeypatch.setattr(chat_turn, "patch_session", lambda *_a, **_k: None)
    monkeypatch.setattr(chat_turn, "insert_retrieval_record", lambda *_a, **_k: "rr-1")
    monkeypatch.setattr(chat_turn, "update_assistant_message", lambda *_a, **_k: None)
    monkeypatch.setattr(chat_turn, "insert_citation_rows", lambda *_a, **_k: 0)

    async def fake_retrieve(*_a, **kwargs):
        captured["retrieve_kwargs"] = kwargs
        return [], [], 0, False, "graph_graphiti_context_v1"

    monkeypatch.setattr(chat_turn, "_retrieve", fake_retrieve)

    asyncio.run(
        chat_turn.run_chat_turn(
            {"redis": AsyncMock(), "database_url": "postgresql://stub/none"},
            workspace_id="ws-1",
            session_id="ses-1",
            user_message_id="user-1",
            assistant_message_id="asst-1",
            turn_id="turn-1",
        )
    )

    assert captured["retrieve_kwargs"] is not None
    assert captured["retrieve_kwargs"]["scope"] == scope
    assert captured["retrieve_kwargs"]["workspace_id"] == "ws-1"


def test_insert_assistant_pending_sql_carries_scope_and_retrieval_mode() -> None:
    """Pin the SQL shape of ``insert_assistant_message_pending`` so a
    future column rename breaks here, not at runtime.

    Spec link: [`apps/migrations/alembic/versions/0009_chat_tables.py`](apps/migrations/alembic/versions/0009_chat_tables.py).
    """
    src = (Path(__file__).parent.parent / "app" / "chat_repo.py").read_text()
    assert "effective_scope_snapshot" in src, (
        "chat_messages.effective_scope_snapshot column must be referenced "
        "by insert_assistant_message_pending"
    )
    assert "retrieval_mode" in src, (
        "chat_messages.retrieval_mode column must be set on insert "
        "(Sprint 6b reads it for GraphRAG-vs-RAG eval)"
    )
