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
    agent_id: str | None = None,
    collection_id: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Return a compact, structured "shape of the graph" snapshot.

    Backs the graph-context grounding document that Sprint 6 injects into
    every chat turn. The shape includes:

    - ``entity_total``, ``edge_total`` — counts (scoped when ``agent_id``,
      ``collection_id``, or ``document_id`` is set).
    - ``entity_types`` — ordered list of ``{name, count, top_examples}``
      where ``top_examples`` are the entity ``canonical_name`` values for
      that type, ordered by degree desc, capped at
      ``max_names_per_type``.
    - ``edge_types`` — ordered list of ``{name, count}``.
    - ``scope_label`` — human label for the grounding document header.

    Cheap (3 grouped queries + 1 indexed select per type) and intended to
    be called per chat turn before the LLM step. Always returns *all*
    entity names for types with at most ``max_names_per_type`` members —
    so a question like "list all locations" can be answered correctly
    when there are <= 25 Locations.
    """
    from app.graph_repo import memory_space_entity_filter_sql

    filt_sql, filt_params = memory_space_entity_filter_sql(
        database_url,
        workspace_id=workspace_id,
        agent_id=agent_id,
        collection_id=collection_id,
        document_id=document_id,
    )
    scoped = bool(filt_sql)
    if agent_id:
        scope_label = "Memory space"
    elif collection_id:
        scope_label = "Collection"
    elif document_id:
        scope_label = "Document"
    else:
        scope_label = "Workspace"

    scoped_cte = f"""
        scoped_entities AS (
          SELECT e.id
          FROM entities e
          WHERE e.workspace_id = %s::uuid
          {filt_sql}
        )
    """
    cte_params: list[Any] = [workspace_id, *filt_params]

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        if scoped:
            entity_total_row = conn.execute(
                f"""
                WITH {scoped_cte}
                SELECT COUNT(*) AS c FROM scoped_entities
                """,
                cte_params,
            ).fetchone()
            edge_total_row = conn.execute(
                f"""
                WITH {scoped_cte}
                SELECT COUNT(*) AS c
                FROM relationships r
                WHERE r.workspace_id = %s::uuid
                  AND r.source_entity_id IN (SELECT id FROM scoped_entities)
                  AND r.target_entity_id IN (SELECT id FROM scoped_entities)
                """,
                [*cte_params, workspace_id],
            ).fetchone()
        else:
            entity_total_row = conn.execute(
                "SELECT COUNT(*) AS c FROM entities WHERE workspace_id = %s::uuid",
                (workspace_id,),
            ).fetchone()
            edge_total_row = conn.execute(
                "SELECT COUNT(*) AS c FROM relationships WHERE workspace_id = %s::uuid",
                (workspace_id,),
            ).fetchone()
        entity_total = int(entity_total_row["c"]) if entity_total_row else 0
        edge_total = int(edge_total_row["c"]) if edge_total_row else 0

        type_rows = conn.execute(
            f"""
            SELECT e.type AS name, COUNT(*) AS count
            FROM entities e
            WHERE e.workspace_id = %s::uuid
            {filt_sql}
            GROUP BY e.type
            ORDER BY COUNT(*) DESC, e.type ASC
            """,
            [workspace_id, *filt_params],
        ).fetchall()

        entity_types: list[dict[str, Any]] = []
        for r in type_rows:
            ttype = r["name"]
            count = int(r["count"])
            if scoped:
                name_rows = conn.execute(
                    f"""
                    WITH {scoped_cte},
                    inc AS (
                      SELECT r.source_entity_id AS entity_id
                      FROM relationships r
                      WHERE r.workspace_id = %s::uuid
                        AND r.source_entity_id IN (SELECT id FROM scoped_entities)
                        AND r.target_entity_id IN (SELECT id FROM scoped_entities)
                      UNION ALL
                      SELECT r.target_entity_id AS entity_id
                      FROM relationships r
                      WHERE r.workspace_id = %s::uuid
                        AND r.source_entity_id IN (SELECT id FROM scoped_entities)
                        AND r.target_entity_id IN (SELECT id FROM scoped_entities)
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
                    WHERE e.workspace_id = %s::uuid
                      AND e.type = %s
                      AND e.id IN (SELECT id FROM scoped_entities)
                    ORDER BY COALESCE(deg.degree, 0) DESC, e.canonical_name ASC
                    LIMIT %s
                    """,
                    [
                        *cte_params,
                        workspace_id,
                        workspace_id,
                        workspace_id,
                        ttype,
                        int(max_names_per_type),
                    ],
                ).fetchall()
            else:
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
                    "truncated_examples": count > len(top_examples),
                }
            )

        if scoped:
            edge_rows = conn.execute(
                f"""
                WITH {scoped_cte}
                SELECT r.type AS name, COUNT(*) AS count
                FROM relationships r
                WHERE r.workspace_id = %s::uuid
                  AND r.source_entity_id IN (SELECT id FROM scoped_entities)
                  AND r.target_entity_id IN (SELECT id FROM scoped_entities)
                GROUP BY r.type
                ORDER BY COUNT(*) DESC, r.type ASC
                """,
                [*cte_params, workspace_id],
            ).fetchall()
        else:
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
        "scope_label": scope_label,
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
