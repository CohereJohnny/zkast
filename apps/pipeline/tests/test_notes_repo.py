"""Atomic notes repo (requires DATABASE_URL + migrated schema)."""

from __future__ import annotations

import os
import uuid

import pytest

from app.notes_repo import delete_note, fetch_note, insert_note, list_notes, update_note
from tests.db_helpers import atomic_notes_table_exists

DEFAULT_WS = "00000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def test_manual_note_roundtrip() -> None:
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0005_notes_graph for this test")
    nid = str(uuid.uuid4())
    insert_note(
        db,
        note_id=nid,
        workspace_id=DEFAULT_WS,
        title="Repo test",
        body="Hello **world**",
        tags=["Alpha", "beta"],
        origin="manual",
        created_by_user_id=None,
        episode_ids=[],
        is_user_edited=False,
    )
    row = fetch_note(db, workspace_id=DEFAULT_WS, note_id=nid)
    assert row is not None
    assert row["title"] == "Repo test"
    assert "alpha" in (row.get("tags") or [])

    rows, total = list_notes(db, workspace_id=DEFAULT_WS, q="Repo", limit=20, offset=0)
    assert total >= 1
    assert any(r["id"] == nid for r in rows)

    update_note(db, workspace_id=DEFAULT_WS, note_id=nid, title="Updated")
    assert fetch_note(db, workspace_id=DEFAULT_WS, note_id=nid)["title"] == "Updated"

    assert delete_note(db, workspace_id=DEFAULT_WS, note_id=nid) is True
    assert fetch_note(db, workspace_id=DEFAULT_WS, note_id=nid) is None
