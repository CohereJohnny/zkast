"""Postgres reads/writes for document_collections."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row


def _uuid_str(row: dict[str, Any], key: str) -> None:
    if row.get(key) is not None:
        row[key] = str(row[key])


def get_or_create_collection(
    database_url: str,
    *,
    workspace_id: str,
    name: str,
    description: str | None = None,
) -> dict[str, Any]:
    """Create-or-get a collection by case-insensitive name within a workspace."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise ValueError("collection_name_required")
    if len(cleaned) > 200:
        raise ValueError("collection_name_too_long")

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT * FROM document_collections
            WHERE workspace_id = %s::uuid AND lower(name) = lower(%s)
            LIMIT 1
            """,
            (workspace_id, cleaned),
        ).fetchone()
        if row:
            _uuid_str(row, "id")
            _uuid_str(row, "workspace_id")
            return row

        cid = str(uuid4())
        row = conn.execute(
            """
            INSERT INTO document_collections (id, workspace_id, name, description)
            VALUES (%s::uuid, %s::uuid, %s, %s)
            RETURNING *
            """,
            (cid, workspace_id, cleaned, (description or "").strip() or None),
        ).fetchone()
        conn.commit()
        assert row
        _uuid_str(row, "id")
        _uuid_str(row, "workspace_id")
        return row


def fetch_collection(
    database_url: str,
    *,
    workspace_id: str,
    collection_id: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT c.*,
                   (SELECT count(*)::int FROM documents d
                    WHERE d.collection_id = c.id) AS document_count
            FROM document_collections c
            WHERE c.id = %s::uuid AND c.workspace_id = %s::uuid
            LIMIT 1
            """,
            (collection_id, workspace_id),
        ).fetchone()
        if not row:
            return None
        _uuid_str(row, "id")
        _uuid_str(row, "workspace_id")
        return row


def list_collections(
    database_url: str,
    *,
    workspace_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT c.*,
                   (SELECT count(*)::int FROM documents d
                    WHERE d.collection_id = c.id) AS document_count
            FROM document_collections c
            WHERE c.workspace_id = %s::uuid
            ORDER BY lower(c.name) ASC
            LIMIT %s
            """,
            (workspace_id, limit),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        r = dict(row)
        _uuid_str(r, "id")
        _uuid_str(r, "workspace_id")
        out.append(r)
    return out


def list_document_ids_for_collection(
    database_url: str,
    *,
    workspace_id: str,
    collection_id: str,
) -> list[str]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT id::text AS id
            FROM documents
            WHERE workspace_id = %s::uuid AND collection_id = %s::uuid
            """,
            (workspace_id, collection_id),
        ).fetchall()
        return [r["id"] for r in rows]


def create_collection(
    database_url: str,
    *,
    workspace_id: str,
    name: str,
    description: str | None = None,
) -> dict[str, Any]:
    """Insert a new collection; raises on duplicate name."""
    return get_or_create_collection(
        database_url,
        workspace_id=workspace_id,
        name=name,
        description=description,
    )
