"""Entity upsert dedup by (workspace, type, canonical_name)."""

from __future__ import annotations

import os
import uuid

import pytest

from app import entities_repo
from tests.db_helpers import atomic_notes_table_exists

DEFAULT_WS = "00000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def test_upsert_same_canonical_reuses_entity() -> None:
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0005_notes_graph for this test")
    g1 = str(uuid.uuid4())
    g2 = str(uuid.uuid4())
    e1 = entities_repo.upsert_entity_from_graphiti(
        db,
        workspace_id=DEFAULT_WS,
        graphiti_uuid=g1,
        name="Acme Corp",
        labels=["Organization"],
        summary="first",
        attributes={},
        episode_id=None,
        note_id=None,
    )
    e2 = entities_repo.upsert_entity_from_graphiti(
        db,
        workspace_id=DEFAULT_WS,
        graphiti_uuid=g2,
        name="acme corp",
        labels=["Organization"],
        summary="second summary",
        attributes={},
        episode_id=None,
        note_id=None,
    )
    assert e1 == e2
