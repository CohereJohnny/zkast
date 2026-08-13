"""Graph + hybrid retrieval honour memory-space (agent) scope."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app import chat_retrieval_graph as graph_mod
from app import chat_retrieval_hybrid as hybrid_mod
from app.chat_intent import IntentClassification, IntentSlots


@pytest.mark.asyncio
async def test_graph_retrieve_passes_agent_scope_to_summarize() -> None:
    settings = SimpleNamespace()
    captured: dict = {}

    def fake_summarize(*_a, **kwargs):
        captured.update(kwargs)
        return {"entity_total": 0, "edge_total": 0, "entity_types": [], "edge_types": []}

    with (
        patch.object(graph_mod, "workspace_graph_store_empty", return_value=False),
        patch.object(graph_mod, "summarize_workspace_graph", fake_summarize),
        patch.object(
            graph_mod,
            "graphiti_for_workspace",
            new_callable=AsyncMock,
            side_effect=RuntimeError("skip graphiti"),
        ),
    ):
        await graph_mod.retrieve(
            settings,
            "postgresql://stub",
            workspace_id="ws",
            query_text="how many locations",
            scope={"agent_id": "agent-abc"},
            top_k=5,
            doc_token_budget=1000,
        )

    assert captured.get("agent_id") == "agent-abc"


@pytest.mark.asyncio
async def test_hybrid_typed_handler_receives_agent_scope() -> None:
    settings = SimpleNamespace()
    captured: dict = {}

    def fake_typed(*_a, **kwargs):
        captured.update(kwargs)
        return [], []

    intent = IntentClassification(kind="aggregation", slots=IntentSlots(entity_types=["Location"]))

    with (
        patch.object(hybrid_mod.chat_intent, "classify", return_value=intent),
        patch.object(hybrid_mod.chat_handler_typed, "answer", fake_typed),
        patch.object(
            hybrid_mod,
            "graph_retrieve",
            new_callable=AsyncMock,
            return_value=([], [], 0, False, "graph_graphiti_context_v1"),
        ),
    ):
        await hybrid_mod.retrieve(
            settings,
            "postgresql://stub",
            workspace_id="ws",
            query_text="how many locations",
            scope={"agent_id": "agent-xyz"},
            top_k=5,
            doc_token_budget=1000,
        )

    assert captured.get("agent_id") == "agent-xyz"
