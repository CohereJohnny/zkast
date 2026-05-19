"""Notes list agent_id filter."""

from __future__ import annotations

import os
import uuid

import pytest

from app.notes_repo import insert_note, list_notes

DEFAULT_WS = "00000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def test_list_notes_without_agent_includes_null_agent() -> None:
    db = os.environ["DATABASE_URL"]
    pdf_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    insert_note(
        db,
        note_id=pdf_id,
        workspace_id=DEFAULT_WS,
        title="PDF note",
        body="pdf",
        tags=[],
        origin="manual",
        created_by_user_id=None,
        episode_ids=[],
        is_user_edited=False,
        agent_id=None,
    )
    north_id = str(uuid.uuid4())
    insert_note(
        db,
        note_id=north_id,
        workspace_id=DEFAULT_WS,
        title="North note",
        body="north",
        tags=[],
        origin="manual",
        created_by_user_id=None,
        episode_ids=[],
        is_user_edited=False,
        agent_id=agent_id,
    )
    rows, _ = list_notes(db, workspace_id=DEFAULT_WS, limit=500, offset=0)
    ids = {r["id"] for r in rows}
    assert pdf_id in ids
    assert north_id in ids


def test_list_notes_agent_scope_excludes_other_agents() -> None:
    db = os.environ["DATABASE_URL"]
    agent_a = str(uuid.uuid4())
    agent_b = str(uuid.uuid4())
    note_a = str(uuid.uuid4())
    note_b = str(uuid.uuid4())
    for nid, aid in ((note_a, agent_a), (note_b, agent_b)):
        insert_note(
            db,
            note_id=nid,
            workspace_id=DEFAULT_WS,
            title=f"Note {aid[:8]}",
            body="x",
            tags=[],
            origin="manual",
            created_by_user_id=None,
            episode_ids=[],
            is_user_edited=False,
            agent_id=aid,
        )
    rows, _total = list_notes(db, workspace_id=DEFAULT_WS, agent_id=agent_a, limit=100, offset=0)
    ids = {r["id"] for r in rows}
    assert note_a in ids
    assert note_b not in ids
    assert all(r.get("agent_id") == agent_a for r in rows if r.get("agent_id"))
