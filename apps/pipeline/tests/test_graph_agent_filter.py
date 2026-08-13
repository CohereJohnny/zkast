"""Graph list agent_id SQL filter."""

from __future__ import annotations

from unittest.mock import patch

from app.graph_repo import _filter_entity_ids_sql, memory_space_entity_filter_sql


def test_filter_entity_ids_sql_scopes_agent_to_documents() -> None:
    agent = "00000000-0000-4000-8000-000000000099"
    docs = ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"]
    sql, params = _filter_entity_ids_sql(
        workspace_id="ws",
        entity_types=None,
        document_id=None,
        tag=None,
        agent_id=agent,
        agent_document_ids=docs,
    )
    assert "e.agent_id" in sql
    assert "ep.document_id = ANY" in sql
    assert "entity_notes" not in sql
    assert agent in params
    assert docs in params


def test_memory_space_entity_filter_sql_resolves_agent_documents() -> None:
    agent = "00000000-0000-4000-8000-000000000099"
    docs = ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"]
    with patch(
        "app.documents_repo.list_document_ids_for_agent",
        return_value=docs,
    ):
        sql, params = memory_space_entity_filter_sql(
            "postgresql://stub",
            workspace_id="ws",
            agent_id=agent,
        )
    assert "ep.document_id = ANY" in sql
    assert docs in params


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
