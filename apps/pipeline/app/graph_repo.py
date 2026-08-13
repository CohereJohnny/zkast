"""Working graph reads for visualization (Postgres canonical)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
def _entity_row_to_node(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "type": row["type"],
        "name": row["canonical_name"],
        "summary": row.get("summary") or "",
        "properties": row.get("properties") or {},
        "aliases": list(row.get("aliases") or []),
        "is_user_edited": bool(row.get("is_user_edited")),
    }


def _rel_row_to_edge(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "source": str(row["source_entity_id"]),
        "target": str(row["target_entity_id"]),
        "type": row["type"],
        "fact": row.get("fact") or "",
        "valid_from": row["valid_from"].isoformat() if row.get("valid_from") else None,
        "valid_to": row["valid_to"].isoformat() if row.get("valid_to") else None,
        "confidence": float(row["confidence"]) if row.get("confidence") is not None else 1.0,
        "origin": row.get("origin") or "generated",
        "is_user_edited": bool(row.get("is_user_edited")),
    }


def _valid_at_clause(valid_at: datetime | None) -> tuple[str, list[Any]]:
    if valid_at is None:
        return "", []
    return (
        """
        AND (r.valid_from IS NULL OR r.valid_from <= %s)
        AND (r.valid_to IS NULL OR r.valid_to >= %s)
        """,
        [valid_at, valid_at],
    )


def _filter_entity_ids_sql(
    *,
    workspace_id: str,
    entity_types: list[str] | None,
    document_id: str | None,
    tag: str | None,
    agent_id: str | None = None,
    agent_document_ids: list[str] | None = None,
    collection_id: str | None = None,
    collection_document_ids: list[str] | None = None,
) -> tuple[str, list[Any]]:
    """Returns SQL fragment AND ... for entities e, and params."""
    _ = workspace_id
    parts: list[str] = []
    params: list[Any] = []
    if entity_types:
        parts.append("e.type = ANY(%s::text[])")
        params.append(entity_types)
    if document_id:
        parts.append(
            """
            EXISTS (
              SELECT 1 FROM entity_episodes ee
              JOIN episodes ep ON ep.id = ee.episode_id
              WHERE ee.entity_id = e.id AND ep.document_id = %s::uuid
            )
            """
        )
        params.append(document_id)
    if agent_id:
        # Memory-space scope matches Naive RAG: entities tied to this agent's
        # imported documents (via entity_episodes) or stamped with agent_id.
        # We intentionally do NOT match workspace-wide entities that only
        # appear in notes without episode provenance from this agent's docs.
        if agent_document_ids is not None and not agent_document_ids:
            parts.append("FALSE")
        elif agent_document_ids:
            parts.append(
                """
                (
                  e.agent_id = %s::uuid
                  OR EXISTS (
                    SELECT 1 FROM entity_episodes ee
                    JOIN episodes ep ON ep.id = ee.episode_id
                    WHERE ee.entity_id = e.id
                      AND ep.document_id = ANY(%s::uuid[])
                  )
                )
                """
            )
            params.extend([agent_id, agent_document_ids])
        else:
            parts.append("e.agent_id = %s::uuid")
            params.append(agent_id)
    elif collection_id:
        if collection_document_ids is not None and not collection_document_ids:
            parts.append("FALSE")
        elif collection_document_ids:
            parts.append(
                """
                (
                  e.collection_id = %s::uuid
                  OR EXISTS (
                    SELECT 1 FROM entity_episodes ee
                    JOIN episodes ep ON ep.id = ee.episode_id
                    WHERE ee.entity_id = e.id
                      AND ep.document_id = ANY(%s::uuid[])
                  )
                )
                """
            )
            params.extend([collection_id, collection_document_ids])
        else:
            parts.append("e.collection_id = %s::uuid")
            params.append(collection_id)
    if tag:
        parts.append(
            """
            EXISTS (
              SELECT 1 FROM entity_notes en
              JOIN atomic_notes n ON n.id = en.note_id
              WHERE en.entity_id = e.id AND %s = ANY(n.tags)
            )
            """
        )
        params.append(tag)
    if not parts:
        return "", []
    return " AND " + " AND ".join(parts), params


def memory_space_entity_filter_sql(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str | None = None,
    collection_id: str | None = None,
    document_id: str | None = None,
    entity_types: list[str] | None = None,
    tag: str | None = None,
) -> tuple[str, list[Any]]:
    """Entity filter for chat/graph memory-space scope (resolves agent/collection documents)."""
    agent_document_ids: list[str] | None = None
    collection_document_ids: list[str] | None = None
    if agent_id:
        from app.documents_repo import list_document_ids_for_agent

        agent_document_ids = list_document_ids_for_agent(
            database_url,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
    elif collection_id:
        from app.documents_repo import list_document_ids_for_collection

        collection_document_ids = list_document_ids_for_collection(
            database_url,
            workspace_id=workspace_id,
            collection_id=collection_id,
        )
    return _filter_entity_ids_sql(
        workspace_id=workspace_id,
        entity_types=entity_types,
        document_id=document_id,
        tag=tag,
        agent_id=agent_id,
        agent_document_ids=agent_document_ids,
        collection_id=collection_id,
        collection_document_ids=collection_document_ids,
    )


def _expand_neighbors(
    conn: psycopg.Connection,
    *,
    workspace_id: str,
    entity_ids: set[str],
    edge_types: list[str] | None,
    valid_at: datetime | None,
) -> set[str]:
    if not entity_ids:
        return set()
    ids = list(entity_ids)
    va_sql, va_params = _valid_at_clause(valid_at)
    et_sql = ""
    et_params: list[Any] = []
    if edge_types:
        et_sql = " AND r.type = ANY(%s::text[])"
        et_params = [edge_types]
    params: list[Any] = [workspace_id, ids, *va_params, *et_params, workspace_id, ids, *va_params, *et_params]
    rows = conn.execute(
        f"""
        SELECT r.target_entity_id AS other
        FROM relationships r
        WHERE r.workspace_id = %s::uuid
          AND r.source_entity_id = ANY(%s::uuid[])
          {va_sql}
          {et_sql}
        UNION
        SELECT r.source_entity_id AS other
        FROM relationships r
        WHERE r.workspace_id = %s::uuid
          AND r.target_entity_id = ANY(%s::uuid[])
          {va_sql}
          {et_sql}
        """,
        params,
    ).fetchall()
    out: set[str] = set()
    for r in rows:
        oid = str(r["other"])
        if oid not in entity_ids:
            out.add(oid)
    return out


def _bfs_entity_ids(
    conn: psycopg.Connection,
    *,
    database_url: str,
    workspace_id: str,
    seed_ids: list[str],
    depth: int,
    node_limit: int,
    entity_types: list[str] | None,
    document_id: str | None,
    tag: str | None,
    agent_id: str | None,
    collection_id: str | None,
    edge_types: list[str] | None,
    valid_at: datetime | None,
) -> tuple[set[str], bool]:
    """Returns (entity_ids, truncated)."""
    filt_sql, filt_params = memory_space_entity_filter_sql(
        database_url,
        workspace_id=workspace_id,
        agent_id=agent_id,
        collection_id=collection_id,
        document_id=document_id,
        entity_types=entity_types,
        tag=tag,
    )
    seeds = [s for s in seed_ids if s]
    if not seeds:
        return set(), False
    q = f"""
        SELECT e.id::text AS id FROM entities e
        WHERE e.workspace_id = %s::uuid AND e.id = ANY(%s::uuid[])
        {filt_sql}
        """
    rows = conn.execute(q, [workspace_id, seeds, *filt_params]).fetchall()
    current = {str(r["id"]) for r in rows}
    truncated = False
    for _ in range(max(0, depth)):
        if len(current) >= node_limit:
            truncated = True
            break
        nbrs = _expand_neighbors(
            conn,
            workspace_id=workspace_id,
            entity_ids=current,
            edge_types=edge_types,
            valid_at=valid_at,
        )
        if not nbrs:
            break
        if filt_sql:
            q2 = f"""
                SELECT e.id::text AS id FROM entities e
                WHERE e.workspace_id = %s::uuid AND e.id = ANY(%s::uuid[])
                {filt_sql}
                """
            rows2 = conn.execute(q2, [workspace_id, list(nbrs), *filt_params]).fetchall()
            nbrs = {str(r["id"]) for r in rows2}
        for nid in nbrs:
            if len(current) >= node_limit:
                truncated = True
                break
            current.add(nid)
        if truncated:
            break
    if len(current) > node_limit:
        current = set(list(current)[:node_limit])
        truncated = True
    return current, truncated


def list_graph(
    database_url: str,
    *,
    workspace_id: str,
    view: str = "overview",
    seed_entity_ids: list[str] | None = None,
    depth: int = 2,
    entity_types: list[str] | None = None,
    edge_types: list[str] | None = None,
    document_id: str | None = None,
    tag: str | None = None,
    agent_id: str | None = None,
    collection_id: str | None = None,
    valid_at: datetime | None = None,
    node_limit: int = 5000,
) -> dict[str, Any]:
    node_limit = max(1, min(node_limit, 25000))
    depth = max(0, min(depth, 10))
    truncated = False

    filt_sql, filt_params = memory_space_entity_filter_sql(
        database_url,
        workspace_id=workspace_id,
        agent_id=agent_id,
        collection_id=collection_id,
        document_id=document_id,
        entity_types=entity_types,
        tag=tag,
    )
    va_sql, va_params = _valid_at_clause(valid_at)
    et_sql = ""
    et_params: list[Any] = []
    if edge_types:
        et_sql = " AND r.type = ANY(%s::text[])"
        et_params = [edge_types]

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        entity_ids: set[str]
        if view == "subgraph" and seed_entity_ids:
            entity_ids, truncated = _bfs_entity_ids(
                conn,
                database_url=database_url,
                workspace_id=workspace_id,
                seed_ids=seed_entity_ids,
                depth=depth,
                node_limit=node_limit,
                entity_types=entity_types,
                document_id=document_id,
                tag=tag,
                agent_id=agent_id,
                collection_id=collection_id,
                edge_types=edge_types,
                valid_at=valid_at,
            )
        else:
            q = f"""
            SELECT e.id::text AS id FROM entities e
            WHERE e.workspace_id = %s::uuid
            {filt_sql}
            ORDER BY e.updated_at DESC
            LIMIT %s
            """
            rows = conn.execute(q, [workspace_id, *filt_params, node_limit]).fetchall()
            entity_ids = {str(r["id"]) for r in rows}
            if len(rows) >= node_limit:
                truncated = True

        if not entity_ids:
            return {"nodes": [], "edges": [], "truncated": truncated}

        id_list = list(entity_ids)
        ent_rows = conn.execute(
            f"""
            SELECT id, workspace_id, type, canonical_name, aliases, summary, properties, is_user_edited
            FROM entities e
            WHERE e.workspace_id = %s::uuid AND e.id = ANY(%s::uuid[])
            {filt_sql}
            """,
            [workspace_id, id_list, *filt_params],
        ).fetchall()
        nodes = [_entity_row_to_node(dict(r)) for r in ent_rows]

        rel_rows = conn.execute(
            f"""
            SELECT id, workspace_id, source_entity_id, target_entity_id, type, fact,
                   valid_from, valid_to, confidence, origin, is_user_edited
            FROM relationships r
            WHERE r.workspace_id = %s::uuid
              AND r.source_entity_id = ANY(%s::uuid[])
              AND r.target_entity_id = ANY(%s::uuid[])
              {va_sql}
              {et_sql}
            """,
            [workspace_id, id_list, id_list, *va_params, *et_params],
        ).fetchall()
        edges = [_rel_row_to_edge(dict(r)) for r in rel_rows]

    return {"nodes": nodes, "edges": edges, "truncated": truncated}


def fetch_entity_brief(database_url: str, *, workspace_id: str, entity_id: str) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT id, workspace_id, type, canonical_name, aliases, summary, properties, is_user_edited
            FROM entities
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            (entity_id, workspace_id),
        ).fetchone()
        return dict(row) if row else None


def get_entity_detail(
    database_url: str,
    *,
    workspace_id: str,
    entity_id: str,
    neighbor_depth: int = 1,
    neighbor_limit: int = 50,
) -> dict[str, Any] | None:
    base = fetch_entity_brief(database_url, workspace_id=workspace_id, entity_id=entity_id)
    if not base:
        return None
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        notes = conn.execute(
            """
            SELECT n.id::text AS id, n.title, n.origin
            FROM entity_notes en
            JOIN atomic_notes n ON n.id = en.note_id
            WHERE en.entity_id = %s::uuid AND n.workspace_id = %s::uuid
            ORDER BY n.updated_at DESC
            LIMIT 200
            """,
            (entity_id, workspace_id),
        ).fetchall()
        episodes = conn.execute(
            """
            SELECT e.id::text AS id, e.document_id::text AS document_id,
                   d.original_filename AS document_name, e.kind, e.text,
                   e.page_start, e.page_end
            FROM entity_episodes ee
            JOIN episodes e ON e.id = ee.episode_id
            JOIN documents d ON d.id = e.document_id
            WHERE ee.entity_id = %s::uuid AND e.workspace_id = %s::uuid
            ORDER BY e.id
            LIMIT 200
            """,
            (entity_id, workspace_id),
        ).fetchall()
        n_ids, _ = _bfs_entity_ids(
            conn,
            database_url=database_url,
            workspace_id=workspace_id,
            seed_ids=[entity_id],
            depth=neighbor_depth,
            node_limit=neighbor_limit,
            entity_types=None,
            document_id=None,
            tag=None,
            agent_id=None,
            collection_id=None,
            edge_types=None,
            valid_at=None,
        )
        n_ids.discard(entity_id)
        neighbors: list[dict[str, Any]] = []
        if n_ids:
            nrow = conn.execute(
                """
                SELECT id::text AS id, type, canonical_name AS name
                FROM entities
                WHERE workspace_id = %s::uuid AND id = ANY(%s::uuid[])
                ORDER BY canonical_name
                LIMIT %s
                """,
                (workspace_id, list(n_ids), neighbor_limit),
            ).fetchall()
            neighbors = [dict(r) for r in nrow]

        rel_rows = conn.execute(
            """
            SELECT r.id, r.source_entity_id, r.target_entity_id, r.type, r.fact,
                   r.valid_from, r.valid_to, r.confidence, r.origin, r.is_user_edited
            FROM relationships r
            WHERE r.workspace_id = %s::uuid
              AND (r.source_entity_id = %s::uuid OR r.target_entity_id = %s::uuid)
            ORDER BY r.id
            LIMIT 500
            """,
            (workspace_id, entity_id, entity_id),
        ).fetchall()
        incident = [_rel_row_to_edge(dict(r)) for r in rel_rows]

    out = _entity_row_to_node(base)
    out["source_notes"] = [dict(r) for r in notes]
    out["source_episodes"] = [dict(r) for r in episodes]
    out["neighbors_summary"] = neighbors
    out["incident_relationships"] = incident
    return out


def count_workspace_entities(database_url: str, *, workspace_id: str) -> int:
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            "SELECT count(*)::int AS c FROM entities WHERE workspace_id = %s::uuid",
            (workspace_id,),
        ).fetchone()
        return int(row[0]) if row else 0
