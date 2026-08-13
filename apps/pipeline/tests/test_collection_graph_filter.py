"""Graph entity filter SQL for collection memory spaces."""

from __future__ import annotations

from app.graph_repo import _filter_entity_ids_sql


def test_collection_filter_uses_collection_id() -> None:
    sql, params = _filter_entity_ids_sql(
        workspace_id="ws",
        entity_types=None,
        document_id=None,
        tag=None,
        collection_id="11111111-1111-4111-8111-111111111111",
        collection_document_ids=["22222222-2222-4222-8222-222222222222"],
    )
    assert "e.collection_id" in sql
    assert "ep.document_id = ANY" in sql
    assert params[0] == "11111111-1111-4111-8111-111111111111"


def test_agent_filter_takes_precedence_shape() -> None:
    sql, params = _filter_entity_ids_sql(
        workspace_id="ws",
        entity_types=None,
        document_id=None,
        tag=None,
        agent_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        agent_document_ids=None,
        collection_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    )
    assert "e.agent_id" in sql
    assert "e.collection_id" not in sql
    assert params == ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"]
