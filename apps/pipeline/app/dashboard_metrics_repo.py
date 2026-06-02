"""Workspace dashboard metrics — counts, storage split, hierarchy, drift."""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.memory_space import list_memory_space_graph_names, memory_space_graph_name
from app.north_repo import (
    fetch_agent_stats,
    fetch_conversation_memory_stats_by_agent,
    list_north_agents,
)
from app.raw_chunk_index import count_raw_chunks
from app.retrieval_embeddings_repo import count_by_kind
from app.retrieval_embeddings_repo import (
    count_orphaned_note_embeddings,
    purge_orphaned_note_embeddings,
)
from app.usage_events_repo import usage_totals_by_source, usage_totals_workspace
from app.workspace_reset import preview_workspace_reset


def _count(conn: psycopg.Connection, sql: str, *params: Any) -> int:
    row = conn.execute(sql, params).fetchone()
    if not row:
        return 0
    return int(next(iter(row.values())))


def _documents_by_source(conn: psycopg.Connection, workspace_id: str) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT source_kind, COUNT(*)::int AS c
        FROM documents WHERE workspace_id = %s::uuid
        GROUP BY source_kind
        """,
        (workspace_id,),
    ).fetchall()
    return {str(r["source_kind"]): int(r["c"]) for r in rows}


def _documents_by_status(conn: psycopg.Connection, workspace_id: str) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT status, COUNT(*)::int AS c
        FROM documents WHERE workspace_id = %s::uuid
        GROUP BY status
        """,
        (workspace_id,),
    ).fetchall()
    return {str(r["status"]): int(r["c"]) for r in rows}


def _ingestion_runs_summary(conn: psycopg.Connection, workspace_id: str) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT ir.status, COUNT(*)::int AS c
        FROM ingestion_runs ir
        JOIN documents d ON d.id = ir.document_id
        WHERE d.workspace_id = %s::uuid
        GROUP BY ir.status
        """,
        (workspace_id,),
    ).fetchall()
    return {str(r["status"]): int(r["c"]) for r in rows}


def _entities_by_agent(conn: psycopg.Connection, workspace_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT agent_id::text, COUNT(*)::int AS c
        FROM entities WHERE workspace_id = %s::uuid
        GROUP BY agent_id
        """,
        (workspace_id,),
    ).fetchall()
    out = []
    for r in rows:
        aid = r.get("agent_id")
        out.append({"agent_id": str(aid) if aid else None, "count": int(r["c"])})
    return out


def _embeddings_by_agent(conn: psycopg.Connection, workspace_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT agent_id::text, index_kind, COUNT(*)::int AS c
        FROM retrieval_embeddings
        WHERE workspace_id = %s::uuid
        GROUP BY agent_id, index_kind
        ORDER BY agent_id NULLS FIRST, index_kind
        """,
        (workspace_id,),
    ).fetchall()
    return [
        {
            "agent_id": str(r["agent_id"]) if r.get("agent_id") else None,
            "index_kind": str(r["index_kind"]),
            "count": int(r["c"]),
        }
        for r in rows
    ]


def _wiki_summary(conn: psycopg.Connection, workspace_id: str) -> dict[str, Any]:
    spaces = _count(
        conn, "SELECT COUNT(*) FROM wiki_spaces WHERE workspace_id = %s::uuid", workspace_id
    )
    pages = _count(
        conn,
        """
        SELECT COUNT(*) FROM wiki_pages wp
        JOIN wiki_spaces ws ON ws.id = wp.wiki_space_id
        WHERE ws.workspace_id = %s::uuid
        """,
        workspace_id,
    )
    return {"spaces": spaces, "pages": pages}


def _chat_summary(conn: psycopg.Connection, workspace_id: str) -> dict[str, Any]:
    sessions = _count(
        conn, "SELECT COUNT(*) FROM chat_sessions WHERE workspace_id = %s::uuid", workspace_id
    )
    messages = _count(
        conn,
        """
        SELECT COUNT(*) FROM chat_messages cm
        JOIN chat_sessions cs ON cs.id = cm.session_id
        WHERE cs.workspace_id = %s::uuid
        """,
        workspace_id,
    )
    return {"sessions": sessions, "messages": messages}


def _scoped_graph_counts(
    conn: psycopg.Connection, workspace_id: str, agent_id: str | None
) -> dict[str, int]:
    if agent_id:
        entities = _count(
            conn,
            "SELECT COUNT(*) FROM entities WHERE workspace_id = %s::uuid AND agent_id = %s::uuid",
            workspace_id,
            agent_id,
        )
        relationships = _count(
            conn,
            """
            SELECT COUNT(*) FROM relationships
            WHERE workspace_id = %s::uuid AND agent_id = %s::uuid
            """,
            workspace_id,
            agent_id,
        )
        maps = _count(
            conn,
            """
            SELECT COUNT(*) FROM graphiti_entity_map
            WHERE workspace_id = %s::uuid AND agent_id = %s::uuid
            """,
            workspace_id,
            agent_id,
        )
    else:
        entities = _count(
            conn,
            """
            SELECT COUNT(*) FROM entities
            WHERE workspace_id = %s::uuid AND agent_id IS NULL
            """,
            workspace_id,
        )
        relationships = _count(
            conn,
            """
            SELECT COUNT(*) FROM relationships
            WHERE workspace_id = %s::uuid AND agent_id IS NULL
            """,
            workspace_id,
        )
        maps = _count(
            conn,
            """
            SELECT COUNT(*) FROM graphiti_entity_map
            WHERE workspace_id = %s::uuid AND agent_id IS NULL
            """,
            workspace_id,
        )
    return {"entities": entities, "relationships": relationships, "graphiti_entity_maps": maps}


async def _falkor_node_counts(
    *,
    falkordb_host: str,
    falkordb_port: int,
    graph_names: list[str],
) -> dict[str, int | None]:
    import redis.asyncio as aioredis

    client = aioredis.Redis(host=falkordb_host, port=falkordb_port, decode_responses=True)
    out: dict[str, int | None] = {}
    try:
        for name in graph_names:
            try:
                # FalkorDB / RedisGraph style count (best-effort).
                result = await client.execute_command(
                    "GRAPH.QUERY",
                    name,
                    "MATCH (n) RETURN count(n) AS c",
                )
                count: int | None = None
                if isinstance(result, list) and len(result) >= 2:
                    data = result[1]
                    if data and isinstance(data[0], list) and data[0]:
                        count = int(data[0][0])
                out[name] = count
            except Exception:  # noqa: BLE001
                out[name] = None
    finally:
        await client.aclose()
    return out


def build_agent_summaries(
    database_url: str,
    *,
    workspace_id: str,
    agents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for agent in agents:
        aid = str(agent["id"])
        stats = fetch_agent_stats(database_url, workspace_id=workspace_id, agent_id=aid)
        conv_memory = fetch_conversation_memory_stats_by_agent(
            database_url, workspace_id=workspace_id, agent_id=aid
        )
        usage = usage_totals_by_source(database_url, workspace_id=workspace_id, agent_id=aid)
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            graph = _scoped_graph_counts(conn, workspace_id, aid)
            notes = _count(
                conn,
                "SELECT COUNT(*) FROM atomic_notes WHERE workspace_id = %s::uuid AND agent_id = %s::uuid",
                workspace_id,
                aid,
            )
            wiki_spaces = _count(
                conn,
                "SELECT COUNT(*) FROM wiki_spaces WHERE workspace_id = %s::uuid AND agent_id = %s::uuid",
                workspace_id,
                aid,
            )
            emb_rows = conn.execute(
                """
                SELECT index_kind, COUNT(*)::int AS c
                FROM retrieval_embeddings
                WHERE workspace_id = %s::uuid AND agent_id = %s::uuid
                GROUP BY index_kind
                """,
                (workspace_id, aid),
            ).fetchall()
        conversations = []
        for cid, mem in conv_memory.items():
            conversations.append(
                {
                    "north_conversation_id": cid,
                    "document_id": mem.get("document_id"),
                    "document_status": mem.get("document_status"),
                    "notes": mem.get("notes", 0),
                    "amem_embeddings": mem.get("amem_embeddings", 0),
                    "ingest_digest": mem.get("ingest_digest"),
                }
            )
        conversations.sort(key=lambda c: c.get("north_conversation_id") or "")
        summaries.append(
            {
                "agent_id": aid,
                "display_name": agent.get("display_name") or aid,
                "external_agent_id": agent.get("external_agent_id"),
                "provider": agent.get("provider") or "north",
                "stats": stats,
                "graph": graph,
                "notes": notes,
                "wiki_spaces": wiki_spaces,
                "embeddings_by_kind": {
                    str(r["index_kind"]): int(r["c"]) for r in emb_rows
                },
                "usage_by_source": usage,
                "memory_space_graph": memory_space_graph_name(workspace_id, aid),
                "conversations": conversations,
            }
        )
    return summaries


def fetch_dashboard_metrics(
    database_url: str,
    *,
    workspace_id: str,
    falkordb_host: str | None = None,
    falkordb_port: int | None = None,
    agent_id: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Build full dashboard payload for workspace (optional agent/conversation filter)."""
    preview = preview_workspace_reset(database_url, workspace_id=workspace_id)
    drift_warnings: list[str] = []
    orphaned_embeddings = count_orphaned_note_embeddings(
        database_url, workspace_id=workspace_id
    )
    if orphaned_embeddings:
        removed = purge_orphaned_note_embeddings(database_url, workspace_id=workspace_id)
        drift_warnings.append(
            f"Removed {removed} orphaned note embedding(s) left after note deletion or re-ingestion"
        )
    raw_chunk = count_raw_chunks(database_url, workspace_id=workspace_id)
    embeddings_by_kind = count_by_kind(database_url, workspace_id=workspace_id)
    usage_workspace = usage_totals_workspace(database_url, workspace_id=workspace_id)
    usage_by_source = usage_totals_by_source(database_url, workspace_id=workspace_id)

    agents = list_north_agents(database_url, workspace_id=workspace_id)
    graph_names = list_memory_space_graph_names(database_url, workspace_id=workspace_id)

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        postgres_extra = {
            "documents_by_source": _documents_by_source(conn, workspace_id),
            "documents_by_status": _documents_by_status(conn, workspace_id),
            "ingestion_runs_by_status": _ingestion_runs_summary(conn, workspace_id),
            "entities_by_agent": _entities_by_agent(conn, workspace_id),
            "embeddings_by_agent": _embeddings_by_agent(conn, workspace_id),
            "wiki": _wiki_summary(conn, workspace_id),
            "chat": _chat_summary(conn, workspace_id),
            "global_graph": _scoped_graph_counts(conn, workspace_id, None),
            "ingestion_logs": _count(
                conn,
                """
                SELECT COUNT(*) FROM ingestion_run_logs irl
                JOIN ingestion_runs ir ON ir.id = irl.ingestion_run_id
                JOIN documents d ON d.id = ir.document_id
                WHERE d.workspace_id = %s::uuid
                """,
                workspace_id,
            ),
        }

    falkor_counts: dict[str, int | None] = {}
    if falkordb_host and falkordb_port is not None:
        try:
            falkor_counts = asyncio.run(
                _falkor_node_counts(
                    falkordb_host=falkordb_host,
                    falkordb_port=falkordb_port,
                    graph_names=graph_names,
                )
            )
        except Exception:  # noqa: BLE001
            falkor_counts = {}

    pg_global_entities = postgres_extra["global_graph"]["entities"]
    pg_global_maps = postgres_extra["global_graph"]["graphiti_entity_maps"]
    global_graph = memory_space_graph_name(workspace_id, None)
    falkor_global = falkor_counts.get(global_graph)
    if falkor_global is not None and pg_global_maps and abs(falkor_global - pg_global_maps) > max(
        5, int(pg_global_maps * 0.25)
    ):
        drift_warnings.append(
            f"Global Falkor node count ({falkor_global}) diverges from graphiti_entity_map ({pg_global_maps})"
        )
    if pg_global_entities and not pg_global_maps:
        drift_warnings.append("Postgres entities exist but no graphiti_entity_map rows (global scope)")

    missing_embeddings = max(0, raw_chunk.get("missing", 0))
    if missing_embeddings:
        drift_warnings.append(f"{missing_embeddings} episode chunks missing raw_chunk embeddings")

    agent_summaries = build_agent_summaries(
        database_url, workspace_id=workspace_id, agents=agents
    )

    selected_agent = None
    selected_conversation = None
    if agent_id:
        selected_agent = next(
            (a for a in agent_summaries if a["agent_id"] == agent_id),
            None,
        )
        if conversation_id and selected_agent:
            selected_conversation = next(
                (
                    c
                    for c in selected_agent.get("conversations") or []
                    if c.get("north_conversation_id") == conversation_id
                ),
                None,
            )

    return {
        "workspace_id": workspace_id,
        "busy": preview.busy,
        "busy_reasons": preview.busy_reasons,
        "counts": preview.counts,
        "postgres": postgres_extra,
        "storage": {
            "postgres_row_estimate": sum(preview.counts.values()),
            "embeddings_by_kind": embeddings_by_kind,
            "raw_chunk_index": raw_chunk,
            "falkor_graphs": [
                {
                    "graph_name": name,
                    "node_count": falkor_counts.get(name),
                    "scope": "global" if name == global_graph else "agent",
                }
                for name in graph_names
            ],
        },
        "usage": {
            "workspace_total": usage_workspace,
            "by_source": usage_by_source,
        },
        "agents": agent_summaries,
        "filters": {
            "agent_id": agent_id,
            "conversation_id": conversation_id,
        },
        "selection": {
            "agent": selected_agent,
            "conversation": selected_conversation,
        },
        "drift_warnings": drift_warnings,
    }
