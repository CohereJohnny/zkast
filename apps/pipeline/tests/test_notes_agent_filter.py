"""Notes list agent_id filter."""

from __future__ import annotations

import uuid

import pytest

from app.notes_repo import delete_note, insert_note, list_notes
from tests.db_helpers import delete_test_north_agent, ensure_test_north_agent, get_database_url

DEFAULT_WS = "00000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(get_database_url() is None, reason="DATABASE_URL not set")


def test_list_notes_without_agent_includes_null_agent() -> None:
    db = get_database_url()
    assert db
    pdf_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    ensure_test_north_agent(db, workspace_id=DEFAULT_WS, agent_id=agent_id)
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
    delete_note(db, workspace_id=DEFAULT_WS, note_id=pdf_id)
    delete_note(db, workspace_id=DEFAULT_WS, note_id=north_id)
    delete_test_north_agent(db, workspace_id=DEFAULT_WS, agent_id=agent_id)


def test_list_notes_agent_scope_excludes_other_agents() -> None:
    db = get_database_url()
    assert db
    agent_a = str(uuid.uuid4())
    agent_b = str(uuid.uuid4())
    note_a = str(uuid.uuid4())
    note_b = str(uuid.uuid4())
    ensure_test_north_agent(db, workspace_id=DEFAULT_WS, agent_id=agent_a)
    ensure_test_north_agent(db, workspace_id=DEFAULT_WS, agent_id=agent_b)
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
    delete_note(db, workspace_id=DEFAULT_WS, note_id=note_a)
    delete_note(db, workspace_id=DEFAULT_WS, note_id=note_b)
    delete_test_north_agent(db, workspace_id=DEFAULT_WS, agent_id=agent_a)
    delete_test_north_agent(db, workspace_id=DEFAULT_WS, agent_id=agent_b)
