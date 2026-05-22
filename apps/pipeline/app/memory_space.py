"""Agent-isolated memory spaces for FalkorDB / Graphiti graphs."""

from __future__ import annotations

import re

import psycopg
from psycopg.rows import dict_row

# Graphiti group_id: alphanumeric, hyphen, underscore only.
_AGENT_SUFFIX_RE = re.compile(r"[^a-zA-Z0-9_-]")


def memory_space_graph_name(workspace_id: str, agent_id: str | None = None) -> str:
    """FalkorDB graph name and Graphiti ``group_id`` for one memory space.

    - ``agent_id`` None → workspace-global graph (PDFs, shared ingestion).
    - ``agent_id`` set → per-agent isolated graph.
    """
    ws = workspace_id.strip()
    if not agent_id or not str(agent_id).strip():
        return ws
    safe = _AGENT_SUFFIX_RE.sub("_", str(agent_id).strip())[:80]
    return f"{ws}__a__{safe}"


def falkor_database_for_memory_space(workspace_id: str, agent_id: str | None = None) -> str:
    """Alias kept for Graphiti driver database= parameter."""
    return memory_space_graph_name(workspace_id, agent_id)


def list_memory_space_graph_names(database_url: str, *, workspace_id: str) -> list[str]:
    """All Falkor graph names for a workspace (global + per-agent)."""
    names = [memory_space_graph_name(workspace_id, None)]
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT id::text AS agent_id FROM north_agents
            WHERE workspace_id = %s::uuid
            ORDER BY display_name ASC
            """,
            (workspace_id,),
        ).fetchall()
    for row in rows:
        aid = str(row.get("agent_id") or "").strip()
        if aid:
            names.append(memory_space_graph_name(workspace_id, aid))
    return names
