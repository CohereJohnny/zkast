"""Graph list agent_id SQL filter."""

from __future__ import annotations

from app.graph_repo import _filter_entity_ids_sql


def test_filter_entity_ids_sql_includes_agent_clause() -> None:
    sql, params = _filter_entity_ids_sql(
        workspace_id="ws",
        entity_types=None,
        document_id=None,
        tag=None,
        agent_id="00000000-0000-4000-8000-000000000099",
    )
    assert "ep.agent_id" in sql
    assert params[-1] == "00000000-0000-4000-8000-000000000099"


def test_filter_entity_ids_sql_empty_without_agent() -> None:
    sql, params = _filter_entity_ids_sql(
        workspace_id="ws",
        entity_types=None,
        document_id=None,
        tag=None,
        agent_id=None,
    )
    assert sql == ""
    assert params == []
