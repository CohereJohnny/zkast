"""B1 — worker-crash reconciler.

Verifies ``list_stalled_active_documents`` returns rows whose ingestion-run
heartbeat is stale, so the cron task in ``app.tasks.reconcile_stuck_documents``
can flip them to ``failed``.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from app.documents_repo import (
    fail_running_ingestion_runs_for_document,
    list_stalled_active_documents,
    update_document,
    update_ingestion_run,
)
from tests.db_helpers import ingestion_run_logs_table_exists

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set",
)


def test_list_stalled_active_documents_includes_stale_heartbeat() -> None:
    db = os.environ["DATABASE_URL"]
    if not ingestion_run_logs_table_exists(db):
        pytest.skip("Run Alembic migrations through 0007_ingestion_observability")
    workspace_id = "00000000-0000-4000-8000-000000000002"
    doc_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    stale_ts = datetime.now(timezone.utc) - timedelta(seconds=300)
    update_ts = datetime.now(timezone.utc) - timedelta(seconds=200)
    try:
        with psycopg.connect(db) as conn:
            conn.execute(
                """
                INSERT INTO documents
                  (id, workspace_id, original_filename, mime_type, byte_size,
                   storage_uri, checksum, status, updated_at)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    doc_id,
                    workspace_id,
                    "stalled.pdf",
                    "application/pdf",
                    1,
                    f"local:/tmp/{doc_id}",
                    uuid.uuid4().hex,
                    "extracting_graph",
                    update_ts,
                ),
            )
            conn.execute(
                """
                INSERT INTO ingestion_runs
                  (id, document_id, status, pipeline_version, llm_provider,
                   llm_model_small, llm_model_large, stats, started_at,
                   last_heartbeat_at)
                VALUES (%s::uuid, %s::uuid, 'running', 'test', 'cohere', '', '',
                        '{}'::jsonb, %s, %s)
                """,
                (run_id, doc_id, stale_ts, stale_ts),
            )
            conn.commit()

        rows = list_stalled_active_documents(db, stale_seconds=90)
        ids = [r["document_id"] for r in rows]
        assert doc_id in ids, f"stalled doc not detected: {rows}"

        # The reconciler would now do the cleanup; simulate it.
        fail_running_ingestion_runs_for_document(db, document_id=doc_id)
        update_document(
            db,
            document_id=doc_id,
            status="failed",
            failure_reason="worker_crashed_during_extracting_graph",
        )
        # And confirm it no longer appears.
        rows_after = list_stalled_active_documents(db, stale_seconds=90)
        assert doc_id not in [r["document_id"] for r in rows_after]
    finally:
        with psycopg.connect(db) as conn:
            conn.execute("DELETE FROM ingestion_runs WHERE document_id = %s::uuid", (doc_id,))
            conn.execute("DELETE FROM documents WHERE id = %s::uuid", (doc_id,))
            conn.commit()
