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
    assert "e.agent_id" in sql
    assert "ep.agent_id" in sql
    assert "n.agent_id" in sql
    assert params.count("00000000-0000-4000-8000-000000000099") == 3


def test_memory_space_graph_name_has_no_hyphens() -> None:
    from app.memory_space import memory_space_graph_name

    name = memory_space_graph_name(
        "00000000-0000-4000-8000-000000000002",
        "3dcf6ba2-cb9a-4be0-a459-fff514234a39",
    )
    assert "-" not in name
    assert "__a__" not in name


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
