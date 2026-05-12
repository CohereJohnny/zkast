"""D3 — surface check for the ``/graph/search`` route shape.

Heavy Graphiti integration is exercised by smoke tests elsewhere. Here we
just confirm the FastAPI route is wired and the request validation works,
using a stubbed Graphiti instance.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app import internal_graph


class _StubGraphiti:
    def __init__(self, edges: list[SimpleNamespace]) -> None:
        self._edges = edges
        self.calls: list[dict[str, object]] = []

    async def search(self, *, query: str, group_ids: list[str], num_results: int):
        self.calls.append({"query": query, "group_ids": group_ids, "num_results": num_results})
        return self._edges


def test_internal_graph_search_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    edges = [
        SimpleNamespace(
            source_node_uuid="src-uuid",
            target_node_uuid="tgt-uuid",
            name="RELATED_TO",
            fact="a relates to b",
            uuid="edge-1",
        ),
    ]

    async def fake_graphiti(_settings, _ws):
        return _StubGraphiti(edges)

    def fake_fetch_id(_db, _gid):
        return "00000000-0000-4000-8000-000000000abc"

    monkeypatch.setattr(internal_graph, "graphiti_for_workspace", fake_graphiti)
    monkeypatch.setattr(
        internal_graph.entities_repo,
        "fetch_entity_id_for_graphiti_uuid",
        fake_fetch_id,
    )

    settings = SimpleNamespace(database_url="postgresql://stub/none")
    app_state = SimpleNamespace(settings=settings)
    request = SimpleNamespace(app=SimpleNamespace(state=app_state))

    response = asyncio.run(
        internal_graph.internal_graph_search(
            workspace_id="00000000-0000-4000-8000-000000000002",  # type: ignore[arg-type]
            request=request,  # type: ignore[arg-type]
            q="ada lovelace",
            limit=5,
        )
    )

    import json

    body = json.loads(response.body.decode())
    assert body["query"] == "ada lovelace"
    assert body["limit"] == 5
    assert len(body["results"]) == 1
    r = body["results"][0]
    assert r["type"] == "RELATED_TO"
    assert r["fact"] == "a relates to b"
    assert r["uuid"] == "edge-1"
