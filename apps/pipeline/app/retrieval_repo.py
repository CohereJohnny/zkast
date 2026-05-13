"""Sprint 6 — ``retrieval_records`` repository.

A ``RetrievalRecord`` row is immutable and **must** be persisted before
the LLM call for the assistant message it grounds (FR-41). The
``chat_turn`` orchestrator owns the call-order invariant; this repo just
provides the bulk insert + reads.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def insert_retrieval_record(
    database_url: str,
    *,
    workspace_id: str,
    message_id: str,
    retrieval_strategy: str,
    query_text: str,
    retrieved_items: list[dict[str, Any]],
    total_candidates: int,
    truncated: bool,
) -> str:
    rid = str(uuid4())
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO retrieval_records (
                id, workspace_id, message_id, retrieval_strategy,
                query_text, retrieved_items, total_candidates, truncated
            )
            VALUES (
                %s::uuid, %s::uuid, %s::uuid, %s,
                %s, %s, %s, %s
            )
            """,
            (
                rid,
                workspace_id,
                message_id,
                retrieval_strategy,
                query_text,
                Json(retrieved_items),
                int(total_candidates),
                bool(truncated),
            ),
        )
        conn.commit()
    return rid


def fetch_retrieval_record_by_message(
    database_url: str,
    *,
    message_id: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT
                id::text AS id,
                workspace_id::text AS workspace_id,
                message_id::text AS message_id,
                retrieval_strategy,
                query_text,
                retrieved_items,
                total_candidates,
                truncated,
                created_at
            FROM retrieval_records
            WHERE message_id = %s::uuid
            """,
            (message_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "message_id": row["message_id"],
        "retrieval_strategy": row["retrieval_strategy"],
        "query_text": row["query_text"],
        "retrieved_items": list(row["retrieved_items"] or []),
        "total_candidates": int(row["total_candidates"]),
        "truncated": bool(row["truncated"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
