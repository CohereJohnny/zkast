"""Note link agent isolation (requires DATABASE_URL + migration 0011)."""

from __future__ import annotations

import uuid

import pytest

from app.notes_repo import add_note_link, delete_note, insert_note
from tests.db_helpers import (
    atomic_notes_table_exists,
    delete_test_north_agent,
    ensure_test_north_agent,
    get_database_url,
    postgres_reachable,
)

DEFAULT_WS = "00000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(
    get_database_url() is None,
    reason=(
        "DATABASE_URL unset or invalid — use e.g. "
        "postgresql://zkast:zkast@127.0.0.1:5432/zkast (not a ... placeholder)"
    ),
)


def _db_or_skip() -> str:
    db = get_database_url()
    assert db is not None
    if not postgres_reachable(db):
        pytest.skip("Postgres not reachable at DATABASE_URL — start docker compose postgres")
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0011 for this test")
    return db


def _insert_manual(db: str, *, note_id: str, agent_id: str | None) -> None:
    if agent_id:
        ensure_test_north_agent(db, workspace_id=DEFAULT_WS, agent_id=agent_id)
    insert_note(
        db,
        note_id=note_id,
        workspace_id=DEFAULT_WS,
        title=f"Note {note_id[:8]}",
        body="body",
        tags=[],
        origin="manual",
        created_by_user_id=None,
        episode_ids=[],
        is_user_edited=False,
        agent_id=agent_id,
    )


def test_same_agent_link_succeeds() -> None:
    db = _db_or_skip()
    agent = str(uuid.uuid4())
    src, tgt = str(uuid.uuid4()), str(uuid.uuid4())
    _insert_manual(db, note_id=src, agent_id=agent)
    _insert_manual(db, note_id=tgt, agent_id=agent)
    try:
        row = add_note_link(
            db,
            workspace_id=DEFAULT_WS,
            source_note_id=src,
            target_note_id=tgt,
            kind="related",
            custom_label=None,
            origin="generated",
            link_reason="test same agent",
            link_strength=0.9,
        )
        assert row.get("id")
    finally:
        delete_note(db, workspace_id=DEFAULT_WS, note_id=src)
        delete_note(db, workspace_id=DEFAULT_WS, note_id=tgt)
        delete_test_north_agent(db, workspace_id=DEFAULT_WS, agent_id=agent)


def test_cross_agent_link_forbidden() -> None:
    db = _db_or_skip()
    agent_a, agent_b = str(uuid.uuid4()), str(uuid.uuid4())
    src, tgt = str(uuid.uuid4()), str(uuid.uuid4())
    _insert_manual(db, note_id=src, agent_id=agent_a)
    _insert_manual(db, note_id=tgt, agent_id=agent_b)
    try:
        with pytest.raises(ValueError, match="cross_agent_link_forbidden"):
            add_note_link(
                db,
                workspace_id=DEFAULT_WS,
                source_note_id=src,
                target_note_id=tgt,
                kind="related",
                custom_label=None,
                origin="generated",
            )
    finally:
        delete_note(db, workspace_id=DEFAULT_WS, note_id=src)
        delete_note(db, workspace_id=DEFAULT_WS, note_id=tgt)
        delete_test_north_agent(db, workspace_id=DEFAULT_WS, agent_id=agent_a)
        delete_test_north_agent(db, workspace_id=DEFAULT_WS, agent_id=agent_b)


def test_self_link_rejected() -> None:
    db = _db_or_skip()
    agent = str(uuid.uuid4())
    nid = str(uuid.uuid4())
    _insert_manual(db, note_id=nid, agent_id=agent)
    try:
        with pytest.raises(ValueError, match="cannot link note to itself"):
            add_note_link(
                db,
                workspace_id=DEFAULT_WS,
                source_note_id=nid,
                target_note_id=nid,
                kind="related",
                custom_label=None,
                origin="generated",
            )
    finally:
        delete_note(db, workspace_id=DEFAULT_WS, note_id=nid)
        delete_test_north_agent(db, workspace_id=DEFAULT_WS, agent_id=agent)


def test_pdf_to_agent_scoped_link_allowed() -> None:
    """One null agent_id (PDF) + one North agent — allowed when research mode is off."""
    db = _db_or_skip()
    agent = str(uuid.uuid4())
    pdf_id, north_id = str(uuid.uuid4()), str(uuid.uuid4())
    _insert_manual(db, note_id=pdf_id, agent_id=None)
    _insert_manual(db, note_id=north_id, agent_id=agent)
    try:
        row = add_note_link(
            db,
            workspace_id=DEFAULT_WS,
            source_note_id=pdf_id,
            target_note_id=north_id,
            kind="related",
            custom_label=None,
            origin="generated",
            link_reason="cross-corpus bridge",
        )
        assert row.get("id")
    finally:
        delete_note(db, workspace_id=DEFAULT_WS, note_id=pdf_id)
        delete_note(db, workspace_id=DEFAULT_WS, note_id=north_id)
        delete_test_north_agent(db, workspace_id=DEFAULT_WS, agent_id=agent)
