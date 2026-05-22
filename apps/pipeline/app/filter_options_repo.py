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
            SELECT type AS name, COUNT(*) AS count
            FROM relationships
            WHERE workspace_id = %s::uuid
            GROUP BY type
            ORDER BY COUNT(*) DESC, type ASC
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


def workspace_graph_store_empty(database_url: str, *, workspace_id: str) -> bool:
    """True when the Postgres working graph has no entities and no relationships."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        ent = conn.execute(
            "SELECT COUNT(*) AS c FROM entities WHERE workspace_id = %s::uuid",
            (workspace_id,),
        ).fetchone()
        rel = conn.execute(
            "SELECT COUNT(*) AS c FROM relationships WHERE workspace_id = %s::uuid",
            (workspace_id,),
        ).fetchone()
    return int(ent["c"] if ent else 0) == 0 and int(rel["c"] if rel else 0) == 0


def summarize_workspace_graph(
    database_url: str,
    *,
    workspace_id: str,
    max_names_per_type: int = 25,
) -> dict[str, Any]:
    """Return a compact, structured "shape of the graph" snapshot.

    Backs the graph-context grounding document that Sprint 6 injects into
    every chat turn. The shape includes:

    - ``entity_total``, ``edge_total`` — workspace-wide counts.
    - ``entity_types`` — ordered list of ``{name, count, top_examples}``
      where ``top_examples`` are the entity ``canonical_name`` values for
      that type, ordered by degree desc, capped at
      ``max_names_per_type``.
    - ``edge_types`` — ordered list of ``{name, count}``.

    Cheap (3 grouped queries + 1 indexed select per type) and intended to
    be called per chat turn before the LLM step. Always returns *all*
    entity names for types with at most ``max_names_per_type`` members —
    so a question like "list all locations" can be answered correctly
    when there are <= 25 Locations.
    """
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        entity_total_row = conn.execute(
            "SELECT COUNT(*) AS c FROM entities WHERE workspace_id = %s::uuid",
            (workspace_id,),
        ).fetchone()
        entity_total = int(entity_total_row["c"]) if entity_total_row else 0

        edge_total_row = conn.execute(
            "SELECT COUNT(*) AS c FROM relationships WHERE workspace_id = %s::uuid",
            (workspace_id,),
        ).fetchone()
        edge_total = int(edge_total_row["c"]) if edge_total_row else 0

        type_rows = conn.execute(
            """
            SELECT type AS name, COUNT(*) AS count
            FROM entities
            WHERE workspace_id = %s::uuid
            GROUP BY type
            ORDER BY COUNT(*) DESC, type ASC
            """,
            (workspace_id,),
        ).fetchall()

        entity_types: list[dict[str, Any]] = []
        for r in type_rows:
            ttype = r["name"]
            count = int(r["count"])
            # Degree-ordered exemplars give the LLM both "what types exist"
            # *and* "which instances of this type matter". We cap names at
            # ``max_names_per_type`` so the grounding document stays small
            # enough to fit comfortably inside the per-turn token budget.
            name_rows = conn.execute(
                """
                WITH inc AS (
                    SELECT source_entity_id AS entity_id
                    FROM relationships
                    WHERE workspace_id = %s::uuid
                    UNION ALL
                    SELECT target_entity_id AS entity_id
                    FROM relationships
                    WHERE workspace_id = %s::uuid
                ),
                deg AS (
                    SELECT entity_id, COUNT(*) AS degree
                    FROM inc
                    GROUP BY entity_id
                )
                SELECT e.canonical_name AS name,
                       COALESCE(deg.degree, 0) AS degree
                FROM entities e
                LEFT JOIN deg ON deg.entity_id = e.id
                WHERE e.workspace_id = %s::uuid AND e.type = %s
                ORDER BY COALESCE(deg.degree, 0) DESC, e.canonical_name ASC
                LIMIT %s
                """,
                (workspace_id, workspace_id, workspace_id, ttype, int(max_names_per_type)),
            ).fetchall()
            top_examples = [str(nr["name"]) for nr in name_rows if nr.get("name")]
            entity_types.append(
                {
                    "name": ttype,
                    "count": count,
                    "top_examples": top_examples,
                    # ``truncated_examples`` lets the LLM know it is seeing
                    # a sample rather than the full list when applicable.
                    "truncated_examples": count > len(top_examples),
                }
            )

        edge_rows = conn.execute(
            """
            SELECT type AS name, COUNT(*) AS count
            FROM relationships
            WHERE workspace_id = %s::uuid
            GROUP BY type
            ORDER BY COUNT(*) DESC, type ASC
            """,
            (workspace_id,),
        ).fetchall()
        edge_types = [
            {"name": str(r["name"]), "count": int(r["count"])} for r in edge_rows
        ]

    return {
        "entity_total": entity_total,
        "edge_total": edge_total,
        "entity_types": entity_types,
        "edge_types": edge_types,
    }


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
