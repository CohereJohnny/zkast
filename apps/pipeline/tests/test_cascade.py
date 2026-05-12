"""Document delete preview + exclusive derivatives."""

from __future__ import annotations

import hashlib
import os
import uuid

import pytest

from app.cascade import execute_exclusive_derivatives_delete, preview_document_delete
from app.documents_repo import delete_document_row, insert_document, insert_episodes, insert_ingestion_run
from app.notes_repo import delete_note, insert_note
from tests.db_helpers import atomic_notes_table_exists

DEFAULT_WS = "00000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def test_preview_and_exclusive_delete() -> None:
    db = os.environ["DATABASE_URL"]
    if not atomic_notes_table_exists(db):
        pytest.skip("Run Alembic migrations through 0005_notes_graph for this test")
    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())
    run_a = str(uuid.uuid4())
    run_b = str(uuid.uuid4())
    ep_a1 = str(uuid.uuid4())
    ep_a2 = str(uuid.uuid4())
    ep_b1 = str(uuid.uuid4())

    chk_a = hashlib.sha256(doc_a.encode()).hexdigest()
    chk_b = hashlib.sha256(doc_b.encode()).hexdigest()

    insert_document(
        db,
        document_id=doc_a,
        workspace_id=DEFAULT_WS,
        original_filename="a.pdf",
        mime_type="application/pdf",
        byte_size=10,
        storage_uri=f"local://{DEFAULT_WS}/{doc_a}.pdf",
        checksum=chk_a,
        replaces_document_id=None,
        status="ready",
    )
    insert_document(
        db,
        document_id=doc_b,
        workspace_id=DEFAULT_WS,
        original_filename="b.pdf",
        mime_type="application/pdf",
        byte_size=10,
        storage_uri=f"local://{DEFAULT_WS}/{doc_b}.pdf",
        checksum=chk_b,
        replaces_document_id=None,
        status="ready",
    )
    insert_ingestion_run(
        db,
        run_id=run_a,
        document_id=doc_a,
        status="succeeded",
        pipeline_version="test",
        llm_provider="cohere",
        llm_model_small="x",
        llm_model_large="y",
        stats={},
    )
    insert_ingestion_run(
        db,
        run_id=run_b,
        document_id=doc_b,
        status="succeeded",
        pipeline_version="test",
        llm_provider="cohere",
        llm_model_small="x",
        llm_model_large="y",
        stats={},
    )
    insert_episodes(
        db,
        workspace_id=DEFAULT_WS,
        document_id=doc_a,
        ingestion_run_id=run_a,
        rows=[(ep_a1, "chunk a1", 1, 1, 0), (ep_a2, "chunk a2", 1, 1, 1)],
    )
    insert_episodes(
        db,
        workspace_id=DEFAULT_WS,
        document_id=doc_b,
        ingestion_run_id=run_b,
        rows=[(ep_b1, "chunk b1", 1, 1, 0)],
    )

    n_exclusive = str(uuid.uuid4())
    n_shared = str(uuid.uuid4())
    insert_note(
        db,
        note_id=n_exclusive,
        workspace_id=DEFAULT_WS,
        title="exclusive",
        body="x",
        tags=[],
        origin="manual",
        created_by_user_id=None,
        episode_ids=[ep_a1],
        is_user_edited=False,
    )
    insert_note(
        db,
        note_id=n_shared,
        workspace_id=DEFAULT_WS,
        title="shared",
        body="y",
        tags=[],
        origin="manual",
        created_by_user_id=None,
        episode_ids=[ep_a2, ep_b1],
        is_user_edited=False,
    )

    prev = preview_document_delete(db, workspace_id=DEFAULT_WS, document_id=doc_a)
    assert n_exclusive in prev["exclusive_note_ids"]
    assert n_shared in prev["shared_note_ids"]

    stats = execute_exclusive_derivatives_delete(db, workspace_id=DEFAULT_WS, document_id=doc_a)
    assert stats["removed_notes"] >= 1

    delete_document_row(db, workspace_id=DEFAULT_WS, document_id=doc_a)

    delete_note(db, workspace_id=DEFAULT_WS, note_id=n_shared)
    delete_document_row(db, workspace_id=DEFAULT_WS, document_id=doc_b)
