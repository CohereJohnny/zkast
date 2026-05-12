"""Repository for the ``entity_evidence`` table (Sprint 5c Phase 2).

Synchronous psycopg helpers wrapped by ``asyncio.to_thread`` from
``tasks.py``. Kept tight on purpose — no joins, no orchestration, just
typed reads + bulk inserts.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


# Cap the quote text to keep the UI blockquotes readable. The extractor
# may emit verbatim sentences that occasionally run very long when a
# Standard's title spans 200+ chars.
_QUOTE_MAX_LEN = 600


def insert_evidence_rows(
    database_url: str,
    *,
    workspace_id: str,
    rows: list[dict[str, Any]],
    method: str = "langextract",
) -> int:
    """Bulk-insert evidence rows. Returns inserted count.

    Each row dict must contain: ``entity_id`` (uuid str), ``document_id``,
    ``episode_id`` (nullable), ``page``, ``char_start``, ``char_end``,
    ``quote``, ``attributes`` (dict).
    """
    if not rows:
        return 0
    inserted = 0
    with psycopg.connect(database_url) as conn:
        for r in rows:
            quote = (r.get("quote") or "")[:_QUOTE_MAX_LEN]
            if not quote.strip():
                continue
            conn.execute(
                """
                INSERT INTO entity_evidence (
                    id, workspace_id, entity_id, document_id, episode_id,
                    page, char_start, char_end, quote, method, attributes
                )
                VALUES (
                    %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    str(uuid4()),
                    workspace_id,
                    r["entity_id"],
                    r["document_id"],
                    r.get("episode_id"),
                    int(r.get("page") or 0),
                    int(r["char_start"]),
                    int(r["char_end"]),
                    quote,
                    method,
                    Json(r.get("attributes") or {}),
                ),
            )
            inserted += 1
        conn.commit()
    return inserted


def list_evidence_for_entity(
    database_url: str,
    *,
    workspace_id: str,
    entity_id: str,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return paged evidence rows for one entity, including the source
    document filename for display."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        total_row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM entity_evidence
            WHERE workspace_id = %s::uuid AND entity_id = %s::uuid
            """,
            (workspace_id, entity_id),
        ).fetchone()
        total = int(total_row["c"]) if total_row else 0

        rows = conn.execute(
            """
            SELECT
                ee.id::text AS id,
                ee.document_id::text AS document_id,
                d.original_filename AS document_filename,
                ee.episode_id::text AS episode_id,
                ee.page,
                ee.char_start,
                ee.char_end,
                ee.quote,
                ee.method,
                ee.attributes,
                ee.created_at
            FROM entity_evidence ee
            JOIN documents d ON d.id = ee.document_id
            WHERE ee.workspace_id = %s::uuid AND ee.entity_id = %s::uuid
            ORDER BY ee.created_at DESC, ee.page ASC
            LIMIT %s OFFSET %s
            """,
            (workspace_id, entity_id, int(limit), int(offset)),
        ).fetchall()

    items = []
    for r in rows:
        items.append(
            {
                "id": r["id"],
                "document_id": r["document_id"],
                "document_filename": r["document_filename"],
                "episode_id": r["episode_id"],
                "page": r["page"],
                "char_start": r["char_start"],
                "char_end": r["char_end"],
                "quote": r["quote"],
                "method": r["method"],
                "attributes": dict(r["attributes"] or {}),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
        )
    return {"items": items, "total": total}


def count_evidence_for_document(
    database_url: str,
    *,
    workspace_id: str,
    document_id: str,
) -> int:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM entity_evidence
            WHERE workspace_id = %s::uuid AND document_id = %s::uuid
            """,
            (workspace_id, document_id),
        ).fetchone()
        return int(row["c"]) if row else 0


def delete_evidence_for_document(database_url: str, *, document_id: str) -> int:
    with psycopg.connect(database_url) as conn:
        cur = conn.execute(
            "DELETE FROM entity_evidence WHERE document_id = %s::uuid",
            (document_id,),
        )
        conn.commit()
        return cur.rowcount or 0
