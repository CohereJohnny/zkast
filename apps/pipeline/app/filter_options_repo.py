"""Read-only helpers for graph + note filter pickers (Sprint 5c Phase 4).

Cheap GROUP BY / ILIKE queries that back the new picklists in the
graph filter bar. Sync psycopg style — same as the rest of the
``apps/pipeline/app/*_repo.py`` modules.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row


def list_entity_type_counts(database_url: str, *, workspace_id: str) -> list[dict[str, Any]]:
    """Return entity types currently present in this workspace, with counts."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT type AS name, COUNT(*) AS count
            FROM entities
            WHERE workspace_id = %s::uuid
            GROUP BY type
            ORDER BY COUNT(*) DESC, type ASC
            """,
            (workspace_id,),
        ).fetchall()
    return [{"name": r["name"], "count": int(r["count"])} for r in rows]


def list_edge_type_counts(database_url: str, *, workspace_id: str) -> list[dict[str, Any]]:
    """Return relationship types currently present in this workspace, with counts."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT rel_type AS name, COUNT(*) AS count
            FROM relationships
            WHERE workspace_id = %s::uuid
            GROUP BY rel_type
            ORDER BY COUNT(*) DESC, rel_type ASC
            """,
            (workspace_id,),
        ).fetchall()
    return [{"name": r["name"], "count": int(r["count"])} for r in rows]


def list_tag_counts(database_url: str, *, workspace_id: str) -> list[dict[str, Any]]:
    """Return distinct atomic-note tags with counts.

    ``atomic_notes.tags`` is a ``TEXT[]`` column with a GIN index. We
    use ``unnest`` to flatten and then ``GROUP BY`` for the per-tag
    counts. Tag values are already lower-cased at insertion time.
    """
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT t AS name, COUNT(*) AS count
            FROM atomic_notes,
                 LATERAL unnest(tags) AS t
            WHERE workspace_id = %s::uuid
            GROUP BY t
            ORDER BY COUNT(*) DESC, t ASC
            """,
            (workspace_id,),
        ).fetchall()
    return [{"name": r["name"], "count": int(r["count"])} for r in rows]


def search_entities_typeahead(
    database_url: str,
    *,
    workspace_id: str,
    q: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Typeahead search over entity names.

    Uses a case-insensitive prefix-or-substring match. Returns each hit
    with an approximate ``degree`` (count of incident relationships) so
    the UI can put the most-connected entities at the top of the
    typeahead list.
    """
    needle = (q or "").strip()
    if not needle:
        return []
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            WITH hits AS (
                SELECT id, canonical_name, type
                FROM entities
                WHERE workspace_id = %s::uuid
                  AND (canonical_name ILIKE %s OR canonical_name ILIKE %s)
                LIMIT 200
            ),
            edge_counts AS (
                SELECT entity_id, COUNT(*) AS degree
                FROM (
                    SELECT source_entity_id AS entity_id
                    FROM relationships
                    WHERE workspace_id = %s::uuid
                    UNION ALL
                    SELECT target_entity_id AS entity_id
                    FROM relationships
                    WHERE workspace_id = %s::uuid
                ) ee
                GROUP BY entity_id
            )
            SELECT
                h.id::text AS id,
                h.canonical_name AS name,
                h.type AS type,
                COALESCE(ec.degree, 0) AS degree
            FROM hits h
            LEFT JOIN edge_counts ec ON ec.entity_id = h.id
            ORDER BY ec.degree DESC NULLS LAST, h.canonical_name ASC
            LIMIT %s
            """,
            (
                workspace_id,
                f"{needle}%",
                f"%{needle}%",
                workspace_id,
                workspace_id,
                int(limit),
            ),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "degree": int(r["degree"] or 0),
        }
        for r in rows
    ]
