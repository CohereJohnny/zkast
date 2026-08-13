"""Postgres repo for graphrag_community_reports.

Graphiti-free (psycopg only) so it's usable from both the graphrag-worker
(persist) and the chat-worker (fetch for ms_graphrag retrieval).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row


def persist_community_reports(
    database_url: str,
    *,
    graphrag_index_id: str,
    workspace_id: str,
    agent_id: str | None,
    reports: list[dict[str, Any]],
) -> int:
    """Replace the reports for an index with the given set. Returns count written."""
    rows = [
        (
            str(uuid4()),
            graphrag_index_id,
            workspace_id,
            agent_id,
            r.get("community"),
            r.get("level"),
            r.get("rank"),
            r.get("title"),
            r.get("summary"),
            r.get("full_content"),
        )
        for r in reports
    ]
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "DELETE FROM graphrag_community_reports WHERE graphrag_index_id=%s::uuid",
            (graphrag_index_id,),
        )
        if rows:
            conn.cursor().executemany(
                """
                INSERT INTO graphrag_community_reports (
                  id, graphrag_index_id, workspace_id, agent_id, community, level,
                  rank, title, summary, full_content
                )
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
        conn.commit()
    return len(rows)


def fetch_reports_for_space(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str | None,
    collection_id: str | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Top community reports (by rank) from the latest READY index for a memory
    space (agent, collection, or whole workspace). Empty if no ready index exists.
    """
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        idx = conn.execute(
            """
            SELECT id FROM graphrag_indexes
            WHERE workspace_id = %s::uuid
              AND agent_id IS NOT DISTINCT FROM %s::uuid
              AND collection_id IS NOT DISTINCT FROM %s::uuid
              AND status = 'ready'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (workspace_id, agent_id, collection_id),
        ).fetchone()
        if not idx:
            return []
        rows = conn.execute(
            """
            SELECT community, level, rank, title, summary, full_content
            FROM graphrag_community_reports
            WHERE graphrag_index_id = %s::uuid
            ORDER BY rank DESC NULLS LAST, level ASC
            LIMIT %s
            """,
            (idx["id"], int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]
