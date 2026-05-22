"""Graph retrieval must not call Graphiti when Postgres graph is empty."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app import chat_retrieval_graph as graph_mod


@pytest.mark.asyncio
async def test_graph_retrieve_skips_graphiti_when_store_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        graph_mod,
        "workspace_graph_store_empty",
        lambda *_a, **_k: True,
    )
    graphiti_mock = AsyncMock()
    monkeypatch.setattr(graph_mod, "graphiti_for_workspace", graphiti_mock)

    items, docs, total, truncated, strategy = await graph_mod.retrieve(
        MagicMock(),
        "postgresql://example",
        workspace_id="00000000-0000-0000-0000-000000000099",
        query_text="How many locations?",
        scope={},
        top_k=10,
        doc_token_budget=4000,
    )

    graphiti_mock.assert_not_called()
    assert items == []
    assert docs == []
    assert total == 0
    assert strategy == graph_mod.GRAPH_STRATEGY
