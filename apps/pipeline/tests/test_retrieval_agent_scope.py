"""Agent_id is passed into embedding search for scoped retrieval modes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app import chat_retrieval_notes_vector as notes_vector
from app import chat_retrieval_raw as raw_module
from app.retrieval_embeddings_repo import INDEX_KIND_NOTE_AMEM, INDEX_KIND_RAW_CHUNK


@pytest.mark.asyncio
async def test_raw_retrieve_passes_agent_id_to_search() -> None:
    settings = SimpleNamespace()
    captured: dict = {}

    def fake_search(*_a, **kwargs):
        captured.update(kwargs)
        return []

    with (
        patch("app.chat_retrieval_raw.resolve_cohere_api_key", return_value="key"),
        patch("app.chat_retrieval_raw.embed_query", new_callable=AsyncMock, return_value=[0.1] * 8),
        patch("app.chat_retrieval_raw.search_by_kind", fake_search),
    ):
        await raw_module.retrieve(
            settings,
            "postgresql://stub",
            workspace_id="ws",
            query_text="test",
            scope={"agent_id": "agent-123"},
            top_k=5,
            doc_token_budget=1000,
        )

    assert captured.get("agent_id") == "agent-123"
    assert captured.get("index_kind") == INDEX_KIND_RAW_CHUNK


@pytest.mark.asyncio
async def test_amem_retrieve_passes_agent_id_to_search() -> None:
    settings = SimpleNamespace()
    captured: dict = {}

    def fake_search(*_a, **kwargs):
        captured.update(kwargs)
        return []

    with (
        patch("app.chat_retrieval_notes_vector.resolve_cohere_api_key", return_value="key"),
        patch("app.chat_retrieval_notes_vector.embed_query", new_callable=AsyncMock, return_value=[0.1] * 8),
        patch("app.chat_retrieval_notes_vector.search_by_kind", fake_search),
    ):
        await notes_vector.retrieve_amem(
            settings,
            "postgresql://stub",
            workspace_id="ws",
            query_text="test",
            scope={"agent_id": "agent-456"},
            top_k=5,
            doc_token_budget=1000,
        )

    assert captured.get("agent_id") == "agent-456"
    assert captured.get("index_kind") == INDEX_KIND_NOTE_AMEM
