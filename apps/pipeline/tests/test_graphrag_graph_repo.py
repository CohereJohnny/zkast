"""Tests for GraphRAG parquet graph loader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.graphrag_graph_repo import list_graphrag_communities, list_graphrag_graph

SPIKE_OUT = Path(__file__).resolve().parents[3] / "spikes" / "ms-graphrag" / "cohere" / "output"


@pytest.mark.skipif(not SPIKE_OUT.joinpath("entities.parquet").exists(), reason="spike artifacts missing")
def test_list_graphrag_graph_from_spike_parquet() -> None:
    row = {
        "workspace_id": "00000000-0000-0000-0000-000000000001",
        "status": "ready",
        "artifact_uri": str(SPIKE_OUT),
    }
    with patch("app.graphrag_graph_repo.fetch_graphrag_index", return_value=row):
        data = list_graphrag_graph(
            "postgresql://unused",
            workspace_id="00000000-0000-0000-0000-000000000001",
            graphrag_index_id="idx-1",
            node_limit=5000,
        )
    assert len(data["nodes"]) > 0
    assert isinstance(data["edges"], list)
    assert data["truncated"] is False
    if (SPIKE_OUT / "communities.parquet").exists():
        assert any(n.get("community") is not None for n in data["nodes"])


@pytest.mark.skipif(not SPIKE_OUT.joinpath("communities.parquet").exists(), reason="spike artifacts missing")
def test_list_graphrag_communities_from_spike() -> None:
    row = {
        "id": "idx-1",
        "workspace_id": "00000000-0000-0000-0000-000000000001",
        "status": "ready",
        "artifact_uri": str(SPIKE_OUT),
    }
    with patch("app.graphrag_graph_repo.fetch_graphrag_index", return_value=row):
        with patch("app.graphrag_graph_repo._fetch_reports_by_index", return_value={}):
            items = list_graphrag_communities(
                "postgresql://unused",
                workspace_id="00000000-0000-0000-0000-000000000001",
                graphrag_index_id="idx-1",
            )
    assert len(items) > 0
    assert "entity_ids" in items[0]
    assert "community" in items[0]


def test_list_graphrag_graph_missing_index() -> None:
    with patch("app.graphrag_graph_repo.fetch_graphrag_index", return_value=None):
        with pytest.raises(LookupError):
            list_graphrag_graph(
                "postgresql://unused",
                workspace_id="00000000-0000-0000-0000-000000000001",
                graphrag_index_id="missing",
            )


def test_list_graphrag_graph_failed_index_raises() -> None:
    row = {
        "workspace_id": "00000000-0000-0000-0000-000000000001",
        "status": "failed",
        "failure_reason": "GraphRAG workflows failed: extract_graph",
    }
    with patch("app.graphrag_graph_repo.fetch_graphrag_index", return_value=row):
        with pytest.raises(LookupError, match="failed"):
            list_graphrag_graph(
                "postgresql://unused",
                workspace_id="00000000-0000-0000-0000-000000000001",
                graphrag_index_id="idx-failed",
            )
