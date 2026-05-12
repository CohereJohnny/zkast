"""Graphiti UUID ↔ entity mapping."""

from __future__ import annotations

import os
import uuid

import pytest

from app import entities_repo
from tests.db_helpers import atomic_notes_table_exists

DEFAULT_WS = "00000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def test_graphiti_uuid_maps_round_trip() -> None:
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0005_notes_graph for this test")
    gid = str(uuid.uuid4())
    eid = entities_repo.upsert_entity_from_graphiti(
        db,
        workspace_id=DEFAULT_WS,
        graphiti_uuid=gid,
        name="Mapper Node",
        labels=["Concept"],
        summary="",
        attributes={},
        episode_id=None,
        note_id=None,
    )
    resolved = entities_repo.fetch_entity_id_for_graphiti_uuid(db, gid)
    assert resolved == eid

    # Idempotent re-insert same graphiti uuid
    eid2 = entities_repo.upsert_entity_from_graphiti(
        db,
        workspace_id=DEFAULT_WS,
        graphiti_uuid=gid,
        name="Mapper Node",
        labels=["Concept"],
        summary="updated",
        attributes={},
        episode_id=None,
        note_id=None,
    )
    assert eid2 == eid
