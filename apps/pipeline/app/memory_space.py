"""Agent- and collection-isolated memory spaces for FalkorDB / Graphiti graphs."""

from __future__ import annotations

import re

import psycopg
from psycopg.rows import dict_row

# FalkorDB fulltext (RediSearch) treats hyphens as NOT operators inside group_id
# filters. Graphiti passes group_id into @group_id:"..." queries, so graph names
# must be alphanumeric + underscore only (no hyphens).
_GRAPH_ID_SAFE_RE = re.compile(r"[^a-zA-Z0-9_]")


def _safe_graph_token(value: str) -> str:
    return _GRAPH_ID_SAFE_RE.sub("_", value.strip())


def memory_space_graph_name(
    workspace_id: str,
    agent_id: str | None = None,
    collection_id: str | None = None,
) -> str:
    """FalkorDB graph name and Graphiti ``group_id`` for one memory space.

    Precedence:
    - ``agent_id`` set → ``{ws}_a_{agentId}`` (North / Slack)
    - else ``collection_id`` set → ``{ws}_c_{collectionId}``
    - else workspace-global ``{ws}``

    UUIDs are normalized (hyphens → underscores) so RediSearch fulltext queries
    issued by Graphiti do not fail with syntax errors.
    """
    ws = _safe_graph_token(workspace_id)
    if agent_id and str(agent_id).strip():
        aid = _safe_graph_token(str(agent_id).strip())[:80]
        return f"{ws}_a_{aid}"
    if collection_id and str(collection_id).strip():
        cid = _safe_graph_token(str(collection_id).strip())[:80]
        return f"{ws}_c_{cid}"
    return ws


def falkor_database_for_memory_space(
    workspace_id: str,
    agent_id: str | None = None,
    collection_id: str | None = None,
) -> str:
    """Alias kept for Graphiti driver database= parameter."""
    return memory_space_graph_name(workspace_id, agent_id, collection_id)


def list_memory_space_graph_names(database_url: str, *, workspace_id: str) -> list[str]:
    """All Falkor graph names for a workspace (global + per-agent + per-collection)."""
    names = [memory_space_graph_name(workspace_id, None)]
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        agent_rows = conn.execute(
            """
            SELECT id::text AS agent_id FROM north_agents
            WHERE workspace_id = %s::uuid
            ORDER BY display_name ASC
            """,
            (workspace_id,),
        ).fetchall()
        collection_rows = conn.execute(
            """
            SELECT id::text AS collection_id FROM document_collections
            WHERE workspace_id = %s::uuid
            ORDER BY name ASC
            """,
            (workspace_id,),
        ).fetchall()
    for row in agent_rows:
        aid = str(row.get("agent_id") or "").strip()
        if aid:
            names.append(memory_space_graph_name(workspace_id, aid))
    for row in collection_rows:
        cid = str(row.get("collection_id") or "").strip()
        if cid:
            names.append(memory_space_graph_name(workspace_id, collection_id=cid))
    return names
