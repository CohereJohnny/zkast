"""Sprint 5 graph + snapshots (requires DATABASE_URL + migrations through 0006)."""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.graph_edit_repo import delete_entity, end_relationship, insert_manual_relationship, merge_entities
from app.graph_repo import count_workspace_entities, list_graph
from app.snapshots_repo import SnapshotError, create_snapshot, delete_snapshot, list_snapshots
from tests.db_helpers import atomic_notes_table_exists, graph_snapshots_table_exists

DEFAULT_WS = "00000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def test_list_graph_overview_truncated() -> None:
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0005_notes_graph for this test")
    out = list_graph(db, workspace_id=DEFAULT_WS, view="overview", node_limit=1)
    assert "nodes" in out and "edges" in out and "truncated" in out
    assert isinstance(out["truncated"], bool)


def test_list_graph_subgraph_shape() -> None:
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0005_notes_graph for this test")
    e1 = str(uuid.uuid4())
    try:
        with psycopg.connect(db) as conn:
            conn.execute(
                """
                INSERT INTO entities (id, workspace_id, type, canonical_name, aliases, summary, properties, is_user_edited)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, false)
                """,
                (e1, DEFAULT_WS, "Concept", f"SubSeed-{e1[:8]}", [], "seed", Json({})),
            )
            conn.commit()
        out = list_graph(
            db,
            workspace_id=DEFAULT_WS,
            view="subgraph",
            seed_entity_ids=[e1],
            depth=1,
            node_limit=500,
        )
        assert "nodes" in out and "edges" in out
        ids = {n["id"] for n in out["nodes"]}
        assert e1 in ids
    finally:
        delete_entity(db, workspace_id=DEFAULT_WS, entity_id=e1)


def test_merge_two_entities_roundtrip() -> None:
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0005_notes_graph for this test")
    e1 = str(uuid.uuid4())
    e2 = str(uuid.uuid4())
    try:
        with psycopg.connect(db) as conn:
            conn.execute(
                """
                INSERT INTO entities (id, workspace_id, type, canonical_name, aliases, summary, properties, is_user_edited)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, false)
                """,
                (e1, DEFAULT_WS, "Concept", f"MergeA-{e1[:8]}", [], "a", Json({})),
            )
            conn.execute(
                """
                INSERT INTO entities (id, workspace_id, type, canonical_name, aliases, summary, properties, is_user_edited)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, false)
                """,
                (e2, DEFAULT_WS, "Concept", f"MergeB-{e2[:8]}", [], "b", Json({})),
            )
            conn.commit()
        merged = merge_entities(
            db,
            workspace_id=DEFAULT_WS,
            survivor_id=e1,
            victim_id=e2,
            field_selection={
                "canonical_name": "survivor",
                "type": "survivor",
                "aliases": "survivor",
                "summary": "survivor",
                "properties": "survivor",
            },
        )
        assert merged is not None
        assert merged["id"] == e1
        with psycopg.connect(db) as conn:
            n = conn.execute("SELECT count(*)::int FROM entities WHERE id = %s::uuid", (e2,)).fetchone()
            assert int(n[0]) == 0
    finally:
        delete_entity(db, workspace_id=DEFAULT_WS, entity_id=e1)


def test_manual_relationship_and_end() -> None:
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0005_notes_graph for this test")
    e1 = str(uuid.uuid4())
    e2 = str(uuid.uuid4())
    try:
        with psycopg.connect(db) as conn:
            conn.execute(
                """
                INSERT INTO entities (id, workspace_id, type, canonical_name, aliases, summary, properties, is_user_edited)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, false)
                """,
                (e1, DEFAULT_WS, "Concept", f"RelA-{e1[:8]}", [], "a", Json({})),
            )
            conn.execute(
                """
                INSERT INTO entities (id, workspace_id, type, canonical_name, aliases, summary, properties, is_user_edited)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, false)
                """,
                (e2, DEFAULT_WS, "Concept", f"RelB-{e2[:8]}", [], "b", Json({})),
            )
            conn.commit()
        rel = insert_manual_relationship(
            db,
            workspace_id=DEFAULT_WS,
            source_entity_id=e1,
            target_entity_id=e2,
            rel_type="RELATED_TO",
            fact="pytest",
        )
        assert rel["origin"] == "manual"
        assert rel["is_user_edited"] is True
        rid = rel["id"]
        assert end_relationship(db, workspace_id=DEFAULT_WS, relationship_id=rid) is True
        with psycopg.connect(db, row_factory=dict_row) as conn:
            row = conn.execute(
                "SELECT valid_to FROM relationships WHERE id = %s::uuid",
                (rid,),
            ).fetchone()
            assert row and row["valid_to"] is not None
    finally:
        delete_entity(db, workspace_id=DEFAULT_WS, entity_id=e1)
        delete_entity(db, workspace_id=DEFAULT_WS, entity_id=e2)


def test_snapshot_empty_graph_rejected() -> None:
    db = os.environ["DATABASE_URL"]
    if not graph_snapshots_table_exists(db):
        pytest.skip("Run Alembic migrations through 0006_graph_snapshots for this test")
    ws = str(uuid.uuid4())
    slug = f"empty-{uuid.uuid4().hex[:10]}"
    with psycopg.connect(db) as conn:
        conn.execute(
            "INSERT INTO workspaces (id, name, slug) VALUES (%s::uuid, %s, %s)",
            (ws, "Empty graph test", slug),
        )
        conn.commit()
    try:
        with pytest.raises(SnapshotError) as ei:
            create_snapshot(db, workspace_id=ws, name="snap-empty", description=None, created_by_user_id=None)
        assert ei.value.code == "business_rule_violation"
    finally:
        with psycopg.connect(db) as conn:
            conn.execute("DELETE FROM workspaces WHERE id = %s::uuid", (ws,))
            conn.commit()


def test_snapshot_create_list_delete() -> None:
    db = os.environ["DATABASE_URL"]
    if not graph_snapshots_table_exists(db) or not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0006_graph_snapshots for this test")
    if count_workspace_entities(db, workspace_id=DEFAULT_WS) == 0:
        pytest.skip("Workspace has no entities; cannot snapshot")
    name = f"snap-test-{uuid.uuid4().hex[:8]}"
    snap = create_snapshot(db, workspace_id=DEFAULT_WS, name=name, description="t", created_by_user_id=None)
    assert snap.get("id")
    items, total = list_snapshots(db, workspace_id=DEFAULT_WS, limit=20, offset=0)
    assert total >= 1
    assert any(x["name"] == name for x in items)
    sid = snap["id"]
    assert delete_snapshot(db, workspace_id=DEFAULT_WS, snapshot_id=sid) is True
