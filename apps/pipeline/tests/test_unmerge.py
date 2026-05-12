"""D1 — entity unmerge restores victim row + survivor field rollback."""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.graph_edit_repo import delete_entity, merge_entities, unmerge_entity
from tests.db_helpers import merge_audit_log_table_exists

DEFAULT_WS = "00000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set",
)


def _insert_entity(db: str, *, eid: str, name: str, summary: str) -> None:
    with psycopg.connect(db) as conn:
        conn.execute(
            """
            INSERT INTO entities (id, workspace_id, type, canonical_name, aliases, summary, properties, is_user_edited)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, false)
            """,
            (eid, DEFAULT_WS, "Concept", name, [], summary, Json({})),
        )
        conn.commit()


def test_entity_unmerge_restores_victim_and_rolls_back_survivor() -> None:
    db = os.environ["DATABASE_URL"]
    if not merge_audit_log_table_exists(db):
        pytest.skip("Run Alembic migrations through 0007_ingestion_observability")
    s = str(uuid.uuid4())
    v = str(uuid.uuid4())
    try:
        _insert_entity(db, eid=s, name=f"Survivor-{s[:6]}", summary="survivor summary")
        _insert_entity(db, eid=v, name=f"Victim-{v[:6]}", summary="victim summary")

        merged = merge_entities(
            db,
            workspace_id=DEFAULT_WS,
            survivor_id=s,
            victim_id=v,
            field_selection={
                "canonical_name": "other",
                "type": "survivor",
                "aliases": "survivor",
                "summary": "other",
                "properties": "survivor",
            },
        )
        assert merged is not None
        # After merge, survivor's canonical_name + summary should now be the
        # victim's values.
        with psycopg.connect(db, row_factory=dict_row) as conn:
            row = conn.execute(
                "SELECT canonical_name, summary FROM entities WHERE id = %s::uuid",
                (s,),
            ).fetchone()
            assert row is not None
            assert row["canonical_name"].startswith("Victim-")
            assert row["summary"] == "victim summary"
            # Victim row deleted.
            n = conn.execute(
                "SELECT count(*)::int FROM entities WHERE id = %s::uuid", (v,)
            ).fetchone()
            assert int(n[0]) == 0

        restored = unmerge_entity(db, workspace_id=DEFAULT_WS, survivor_id=s)
        assert restored is not None
        assert str(restored["id"]) == v

        with psycopg.connect(db, row_factory=dict_row) as conn:
            srow = conn.execute(
                "SELECT canonical_name, summary FROM entities WHERE id = %s::uuid",
                (s,),
            ).fetchone()
            assert srow is not None
            assert srow["canonical_name"].startswith("Survivor-")
            assert srow["summary"] == "survivor summary"
    finally:
        delete_entity(db, workspace_id=DEFAULT_WS, entity_id=s)
        delete_entity(db, workspace_id=DEFAULT_WS, entity_id=v)
