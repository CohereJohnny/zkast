"""Orphaned note embedding cleanup."""

from __future__ import annotations

import os
import uuid

import pytest

from app.notes_repo import delete_note, insert_note
from app.retrieval_embeddings_repo import (
    INDEX_KIND_NOTE_AMEM,
    count_orphaned_note_embeddings,
    purge_orphaned_note_embeddings,
    upsert_embedding,
)
from tests.db_helpers import atomic_notes_table_exists

DEFAULT_WS = "00000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def test_delete_note_removes_amem_embedding() -> None:
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0005_notes_graph for this test")
    note_id = str(uuid.uuid4())
    insert_note(
        db,
        note_id=note_id,
        workspace_id=DEFAULT_WS,
        title="orphan test",
        body="body",
        tags=[],
        origin="manual",
    )
    upsert_embedding(
        db,
        workspace_id=DEFAULT_WS,
        index_kind=INDEX_KIND_NOTE_AMEM,
        source_kind="atomic_note",
        source_id=note_id,
        text="amem text",
        embedding=[0.0] * 1536,
        agent_id=None,
    )
    assert delete_note(db, workspace_id=DEFAULT_WS, note_id=note_id) is True
    assert count_orphaned_note_embeddings(db, workspace_id=DEFAULT_WS) == 0


def test_purge_orphaned_note_embeddings() -> None:
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0005_notes_graph for this test")
    upsert_embedding(
        db,
        workspace_id=DEFAULT_WS,
        index_kind=INDEX_KIND_NOTE_AMEM,
        source_kind="atomic_note",
        source_id="00000000-0000-4000-8000-000099999999",
        text="stale",
        embedding=[0.0] * 1536,
    )
    before = count_orphaned_note_embeddings(db, workspace_id=DEFAULT_WS)
    assert before >= 1
    removed = purge_orphaned_note_embeddings(db, workspace_id=DEFAULT_WS)
    assert removed >= 1
    assert count_orphaned_note_embeddings(db, workspace_id=DEFAULT_WS) == 0
