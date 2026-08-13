"""Load MS GraphRAG entity/relationship graphs from parquet artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.graphrag_index_repo import fetch_graphrag_index, fetch_latest_index


def _artifact_dir(index_row: dict[str, Any]) -> Path:
    uri = (index_row.get("artifact_uri") or "").strip()
    if not uri:
        raise FileNotFoundError("GraphRAG index has no artifact_uri")
    return Path(uri)


def _resolve_index_row(
    database_url: str,
    *,
    workspace_id: str,
    graphrag_index_id: str | None = None,
    agent_id: str | None = None,
    collection_id: str | None = None,
    require_ready: bool = True,
) -> dict[str, Any] | None:
    if graphrag_index_id:
        row = fetch_graphrag_index(database_url, index_id=graphrag_index_id)
        if not row or str(row.get("workspace_id")) != workspace_id:
            raise LookupError("GraphRAG index not found")
    else:
        row = fetch_latest_index(
            database_url,
            workspace_id=workspace_id,
            agent_id=agent_id,
            collection_id=collection_id,
        )
        if not row:
            return None
    if require_ready and row.get("status") != "ready":
        return None
    return row


def _load_entity_community_map(out_dir: Path) -> dict[str, int]:
    """Map GraphRAG entity uuid -> community id from communities.parquet."""
    path = out_dir / "communities.parquet"
    if not path.exists():
        return {}
    import pyarrow.parquet as pq  # noqa: WPS433

    table = pq.read_table(path, columns=["community", "entity_ids"])
    mapping: dict[str, int] = {}
    for row in table.to_pylist():
        comm = row.get("community")
        if comm is None:
            continue
        try:
            cidx = int(comm)
        except (TypeError, ValueError):
            continue
        for eid in row.get("entity_ids") or []:
            if eid:
                mapping[str(eid)] = cidx
    return mapping


def _load_communities_parquet(out_dir: Path) -> list[dict[str, Any]]:
    path = out_dir / "communities.parquet"
    if not path.exists():
        return []
    import pyarrow.parquet as pq  # noqa: WPS433

    table = pq.read_table(
        path,
        columns=["community", "level", "title", "entity_ids", "relationship_ids", "size"],
    )
    out: list[dict[str, Any]] = []
    for row in table.to_pylist():
        comm = row.get("community")
        if comm is None:
            continue
        entity_ids = [str(x) for x in (row.get("entity_ids") or []) if x]
        out.append(
            {
                "community": int(comm),
                "level": int(row["level"]) if row.get("level") is not None else 0,
                "title": str(row.get("title") or f"Community {comm}"),
                "size": int(row.get("size") or len(entity_ids)),
                "entity_ids": entity_ids,
                "relationship_ids": [str(x) for x in (row.get("relationship_ids") or []) if x],
            }
        )
    out.sort(key=lambda c: (-int(c.get("size") or 0), int(c.get("community") or 0)))
    return out


def _fetch_reports_by_index(database_url: str, *, graphrag_index_id: str) -> dict[int, dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT community, level, rank, title, summary, full_content
            FROM graphrag_community_reports
            WHERE graphrag_index_id = %s::uuid
            ORDER BY rank DESC NULLS LAST
            """,
            (graphrag_index_id,),
        ).fetchall()
    by_comm: dict[int, dict[str, Any]] = {}
    for r in rows:
        comm = r.get("community")
        if comm is None:
            continue
        cidx = int(comm)
        if cidx not in by_comm:
            by_comm[cidx] = dict(r)
    return by_comm


def list_graphrag_graph(
    database_url: str,
    *,
    workspace_id: str,
    graphrag_index_id: str | None = None,
    agent_id: str | None = None,
    collection_id: str | None = None,
    community_id: int | None = None,
    node_limit: int = 5000,
) -> dict[str, Any]:
    """Return ``{nodes, edges, truncated}`` in the same shape as ``graph_repo.list_graph``."""
    if graphrag_index_id:
        row = fetch_graphrag_index(database_url, index_id=graphrag_index_id)
        if not row or str(row.get("workspace_id")) != workspace_id:
            raise LookupError("GraphRAG index not found")
        if row.get("status") != "ready":
            status = str(row.get("status") or "unknown")
            reason = (row.get("failure_reason") or "").strip()
            msg = f"GraphRAG index is {status}"
            if reason:
                msg = f"{msg}: {reason}"
            raise LookupError(msg)
    else:
        row = _resolve_index_row(
            database_url,
            workspace_id=workspace_id,
            graphrag_index_id=None,
            agent_id=agent_id,
            collection_id=collection_id,
        )
        if not row:
            return {"nodes": [], "edges": [], "truncated": False}

    out_dir = _artifact_dir(row)
    entities_path = out_dir / "entities.parquet"
    relationships_path = out_dir / "relationships.parquet"
    if not entities_path.exists():
        raise FileNotFoundError(f"Missing entities parquet at {entities_path}")

    import pyarrow.parquet as pq  # noqa: WPS433

    entity_community = _load_entity_community_map(out_dir)
    ent_table = pq.read_table(entities_path, columns=["id", "title", "type", "description"])
    ent_rows = ent_table.to_pylist()

    if community_id is not None:
        allowed = {eid for eid, c in entity_community.items() if c == community_id}
        ent_rows = [r for r in ent_rows if str(r.get("id") or "") in allowed]

    truncated = len(ent_rows) > node_limit
    if truncated:
        ent_rows = ent_rows[:node_limit]

    title_to_id: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    id_set: set[str] = set()
    for r in ent_rows:
        eid = str(r.get("id") or "").strip()
        if not eid:
            continue
        title = str(r.get("title") or eid).strip()
        etype = str(r.get("type") or "entity").strip().lower()
        desc = str(r.get("description") or "").strip()
        if title and title not in title_to_id:
            title_to_id[title] = eid
        id_set.add(eid)
        comm = entity_community.get(eid)
        node: dict[str, Any] = {
            "id": eid,
            "name": title or eid,
            "type": etype,
            "summary": desc[:500] if desc else None,
        }
        if comm is not None:
            node["community"] = comm
        nodes.append(node)

    edges: list[dict[str, Any]] = []
    if relationships_path.exists() and id_set:
        rel_table = pq.read_table(
            relationships_path,
            columns=["id", "source", "target", "description"],
        )
        for r in rel_table.to_pylist():
            rid = str(r.get("id") or "").strip()
            src_title = str(r.get("source") or "").strip()
            tgt_title = str(r.get("target") or "").strip()
            src = title_to_id.get(src_title)
            tgt = title_to_id.get(tgt_title)
            if not src or not tgt or src not in id_set or tgt not in id_set:
                continue
            fact = str(r.get("description") or "").strip()
            edges.append(
                {
                    "id": rid or f"{src}:{tgt}",
                    "source": src,
                    "target": tgt,
                    "type": "related",
                    "fact": fact or None,
                }
            )

    return {"nodes": nodes, "edges": edges, "truncated": truncated}


def list_graphrag_communities(
    database_url: str,
    *,
    workspace_id: str,
    graphrag_index_id: str | None = None,
    agent_id: str | None = None,
    collection_id: str | None = None,
) -> list[dict[str, Any]]:
    row = _resolve_index_row(
        database_url,
        workspace_id=workspace_id,
        graphrag_index_id=graphrag_index_id,
        agent_id=agent_id,
        collection_id=collection_id,
    )
    if not row:
        return []

    out_dir = _artifact_dir(row)
    communities = _load_communities_parquet(out_dir)
    reports = _fetch_reports_by_index(database_url, graphrag_index_id=str(row["id"]))

    merged: list[dict[str, Any]] = []
    for c in communities:
        cidx = int(c["community"])
        rep = reports.get(cidx) or {}
        excerpt = (rep.get("summary") or rep.get("full_content") or "")[:400]
        merged.append(
            {
                **c,
                "report_title": rep.get("title"),
                "report_rank": rep.get("rank"),
                "report_excerpt": excerpt or None,
            }
        )
    return merged


def get_graphrag_entity_detail(
    database_url: str,
    *,
    workspace_id: str,
    entity_id: str,
    graphrag_index_id: str | None = None,
    agent_id: str | None = None,
    collection_id: str | None = None,
) -> dict[str, Any] | None:
    row = _resolve_index_row(
        database_url,
        workspace_id=workspace_id,
        graphrag_index_id=graphrag_index_id,
        agent_id=agent_id,
        collection_id=collection_id,
    )
    if not row:
        return None

    out_dir = _artifact_dir(row)
    entities_path = out_dir / "entities.parquet"
    if not entities_path.exists():
        return None

    import pyarrow.parquet as pq  # noqa: WPS433

    entity_community = _load_entity_community_map(out_dir)
    ent_table = pq.read_table(entities_path, columns=["id", "title", "type", "description"])
    target = None
    for r in ent_table.to_pylist():
        if str(r.get("id") or "") == entity_id:
            target = r
            break
    if not target:
        return None

    title = str(target.get("title") or entity_id).strip()
    etype = str(target.get("type") or "entity").strip().lower()
    desc = str(target.get("description") or "").strip()
    comm = entity_community.get(entity_id)

    report: dict[str, Any] | None = None
    if comm is not None:
        reports = _fetch_reports_by_index(database_url, graphrag_index_id=str(row["id"]))
        rep = reports.get(int(comm))
        if rep:
            content = (rep.get("full_content") or rep.get("summary") or "")[:2000]
            report = {
                "community": comm,
                "title": rep.get("title"),
                "rank": rep.get("rank"),
                "excerpt": content,
            }

    return {
        "id": entity_id,
        "name": title,
        "type": etype,
        "description": desc,
        "community": comm,
        "community_report": report,
        "graphrag_index_id": str(row["id"]),
    }
