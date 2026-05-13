"""Sprint 6b / TD-015 — depth-bounded path traversal handler.

Answers "how is A related to B" / "what connects A and B" / "path
from A to B" style queries by running an actual graph traversal over
the workspace's ``entities`` + ``relationships`` tables.

Implementation notes:

- BFS from each endpoint candidate up to ``max_depth`` (default 3).
  Stops as soon as the other endpoint is found.
- Uses Postgres (not Graphiti / FalkorDB) because the
  ``relationships`` table is the source of truth for the working
  graph and lets us walk both directions with a simple SQL query.
- Each edge on the path is rendered with its ``type`` and ``fact`` so
  the LLM can quote the path verbatim.
- Returns at most ``max_paths`` paths to keep the document inside the
  token budget; if none exist, returns an empty result and the hybrid
  strategy falls back to the graph retrieval path.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.chat_intent import IntentClassification
from app.cohere_chat import ChatDocument

logger = logging.getLogger(__name__)


PATH_STRATEGY = "hybrid_path_v1"


def _resolve_entity_id(
    conn: psycopg.Connection,
    workspace_id: str,
    canonical_name: str,
) -> str | None:
    """Resolve a canonical name to its entity id within the workspace."""
    row = conn.execute(
        """
        SELECT id::text AS id
        FROM entities
        WHERE workspace_id = %s::uuid
          AND lower(canonical_name) = lower(%s)
        LIMIT 1
        """,
        (workspace_id, canonical_name),
    ).fetchone()
    if row:
        return str(row[0])
    # Fallback: case-insensitive ``LIKE`` so "Probabilistic Safety
    # Assessment" can match "Probabilistic Safety Assessment (PSA)" or
    # similar aliased forms.
    row = conn.execute(
        """
        SELECT id::text AS id
        FROM entities
        WHERE workspace_id = %s::uuid
          AND canonical_name ILIKE %s
        ORDER BY length(canonical_name) ASC
        LIMIT 1
        """,
        (workspace_id, f"%{canonical_name}%"),
    ).fetchone()
    if row:
        return str(row[0])
    return None


def _entity_name(conn: psycopg.Connection, entity_id: str) -> str:
    row = conn.execute(
        "SELECT canonical_name FROM entities WHERE id = %s::uuid LIMIT 1",
        (entity_id,),
    ).fetchone()
    return str(row[0]) if row else entity_id


def _neighbors(
    conn: psycopg.Connection,
    workspace_id: str,
    entity_id: str,
) -> list[dict[str, Any]]:
    """Return all incident edges + neighbour ids in either direction."""
    rows = conn.execute(
        """
        SELECT
            id::text AS rel_id,
            source_entity_id::text AS source_id,
            target_entity_id::text AS target_id,
            type,
            fact
        FROM relationships
        WHERE workspace_id = %s::uuid
          AND (source_entity_id = %s::uuid OR target_entity_id = %s::uuid)
        """,
        (workspace_id, entity_id, entity_id),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        other = (
            r["target_id"] if r["source_id"] == entity_id else r["source_id"]
        )
        out.append(
            {
                "rel_id": str(r["rel_id"]),
                "source_id": str(r["source_id"]),
                "target_id": str(r["target_id"]),
                "other_id": str(other),
                "type": str(r["type"]) if r["type"] else "RELATES_TO",
                "fact": str(r["fact"]) if r.get("fact") else "",
            }
        )
    return out


def _bfs_paths(
    conn: psycopg.Connection,
    workspace_id: str,
    start_id: str,
    end_id: str,
    *,
    max_depth: int = 3,
    max_paths: int = 5,
) -> list[list[dict[str, Any]]]:
    """Return up to ``max_paths`` paths (each a list of edges) from
    ``start_id`` to ``end_id`` of length ≤ ``max_depth``."""
    if start_id == end_id:
        return []

    # ``(node_id, path_so_far)`` queue. ``path_so_far`` is a list of
    # edge dicts; node identity along the way is encoded by the
    # alternating ``other_id`` values on each edge.
    queue: deque[tuple[str, list[dict[str, Any]]]] = deque([(start_id, [])])
    paths: list[list[dict[str, Any]]] = []

    while queue and len(paths) < max_paths:
        node, path = queue.popleft()
        if len(path) >= max_depth:
            continue
        edges = _neighbors(conn, workspace_id, node)
        visited_ids = {start_id}
        for e in path:
            visited_ids.add(e["source_id"])
            visited_ids.add(e["target_id"])

        for edge in edges:
            nxt = edge["other_id"]
            if nxt == end_id:
                paths.append(path + [edge])
                if len(paths) >= max_paths:
                    break
                continue
            if nxt in visited_ids:
                continue
            queue.append((nxt, path + [edge]))

    return paths


def _render_path(
    conn: psycopg.Connection,
    start_id: str,
    end_name: str,
    start_name: str,
    edges: list[dict[str, Any]],
) -> str:
    """Render a list of edges as ``A -[REL]-> B -[REL]-> C``.

    The traversal stores each edge's full ``source_id`` / ``target_id``
    pair plus ``other_id`` (the side opposite the node we entered from).
    Walking the path means alternating which side we step onto, keyed
    by ``cur_id``.
    """
    pieces: list[str] = [start_name]
    cur_id = start_id
    for edge in edges:
        nxt_id = edge["target_id"] if edge["source_id"] == cur_id else edge["source_id"]
        nxt_name = _entity_name(conn, nxt_id)
        pieces.append(f"-[{edge['type']}]->")
        pieces.append(nxt_name)
        cur_id = nxt_id
    if pieces[-1] != end_name:
        pieces.append(f"(target={end_name})")
    return " ".join(pieces)


def answer(
    database_url: str,
    *,
    workspace_id: str,
    intent: IntentClassification,
    max_depth: int = 3,
    max_paths: int = 5,
) -> tuple[list[dict[str, Any]], list[ChatDocument]]:
    """Return ``(retrieved_items, documents)`` for the multi-hop path
    answer. Empty if fewer than two endpoints can be resolved or if no
    path is found within ``max_depth`` hops.
    """
    names = list(intent.slots.mentioned_entities or [])
    if len(names) < 2:
        return [], []

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        # Resolve every pair of endpoints we can identify and merge
        # their path results. With more than 2 mentioned entities we
        # only look at the first 2 to keep the answer focused; a future
        # iteration could enumerate all pairwise paths.
        a_name = names[0]
        b_name = names[1]
        a_id = _resolve_entity_id(conn, workspace_id, a_name)
        b_id = _resolve_entity_id(conn, workspace_id, b_name)
        if not a_id or not b_id or a_id == b_id:
            return [], []

        paths = _bfs_paths(
            conn,
            workspace_id,
            a_id,
            b_id,
            max_depth=max_depth,
            max_paths=max_paths,
        )
        if not paths:
            # Try the reverse direction too — some relationships are
            # directed, and BFS from the other endpoint may reach a
            # path the first direction missed.
            paths = _bfs_paths(
                conn,
                workspace_id,
                b_id,
                a_id,
                max_depth=max_depth,
                max_paths=max_paths,
            )
            if not paths:
                return [], []
            # Re-render with the original (a, b) framing.
            rendered = [
                _render_path(conn, b_id, a_name, b_name, p) for p in paths
            ]
        else:
            rendered = [
                _render_path(conn, a_id, b_name, a_name, p) for p in paths
            ]

        lines = [
            f"Workspace path traversal from '{a_name}' to '{b_name}' "
            f"(deterministic, depth ≤ {max_depth}, found {len(paths)} path(s)):"
        ]
        for idx, line in enumerate(rendered, start=1):
            lines.append(f"  Path {idx}: {line}")
        # Surface the fact text for each edge so the LLM can quote it.
        for idx, p in enumerate(paths, start=1):
            for j, edge in enumerate(p, start=1):
                fact = edge.get("fact") or ""
                if fact:
                    lines.append(
                        f"    Path {idx} edge {j} ({edge['type']}): {fact}"
                    )
        lines.append(
            "Treat these paths as authoritative connections between the "
            "two entities. Use them to answer the user's question; the "
            "supplementary graph snippets below are context only."
        )
        text = "\n".join(lines)
        doc = ChatDocument(
            id="typed_path:traversal",
            text=text,
            title="Graph path traversal",
            metadata={
                "kind": "typed_path",
                "from": a_name,
                "to": b_name,
                "max_depth": str(max_depth),
            },
        )
        item = {
            "kind": "typed_path",
            "id": f"path:{a_id}->{b_id}",
            "type": "path",
            "score": 1.0,
            "excerpt": text[:2000],
            "endpoints": {"from": a_name, "to": b_name},
            "paths": [
                [
                    {
                        "type": e["type"],
                        "fact": e["fact"],
                        "source_id": e["source_id"],
                        "target_id": e["target_id"],
                    }
                    for e in p
                ]
                for p in paths
            ],
        }
        return [item], [doc]
