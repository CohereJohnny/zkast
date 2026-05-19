"""Note link agent isolation (requires DATABASE_URL + migration 0011)."""

from __future__ import annotations

import os
import uuid

import pytest

from app.notes_repo import add_note_link, delete_note, insert_note
from tests.db_helpers import atomic_notes_table_exists

DEFAULT_WS = "00000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def _insert_manual(db: str, *, note_id: str, agent_id: str | None) -> None:
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
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0011 for this test")
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


def test_cross_agent_link_forbidden() -> None:
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0011 for this test")
    src, tgt = str(uuid.uuid4()), str(uuid.uuid4())
    _insert_manual(db, note_id=src, agent_id=str(uuid.uuid4()))
    _insert_manual(db, note_id=tgt, agent_id=str(uuid.uuid4()))
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


def test_self_link_rejected() -> None:
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0011 for this test")
    nid = str(uuid.uuid4())
    _insert_manual(db, note_id=nid, agent_id=str(uuid.uuid4()))
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


def test_pdf_to_agent_scoped_link_allowed() -> None:
    """One null agent_id (PDF) + one North agent — allowed when research mode is off."""
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0011 for this test")
    pdf_id, north_id = str(uuid.uuid4()), str(uuid.uuid4())
    _insert_manual(db, note_id=pdf_id, agent_id=None)
    _insert_manual(db, note_id=north_id, agent_id=str(uuid.uuid4()))
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
