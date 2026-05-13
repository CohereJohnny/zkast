"""Sprint 6b — GraphRAG retrieval over zettelkasten / graph artifacts.

This is the Sprint 6 retrieval path, factored out of
``chat_turn._retrieve`` so the ``retrieval_mode`` dispatcher in
``chat_turn`` can route to it explicitly. Behaviour is preserved:

- Always prepend a synthesized ``graph_context:workspace_shape``
  ``ChatDocument`` (typed counts + named exemplars from
  ``filter_options_repo.summarize_workspace_graph``) so aggregation
  questions get authoritative numbers.
- Run Graphiti hybrid search (BM25 + vector + Cohere rerank) for the
  top-K relationship facts.
- Apply optional scope filters (document, tag, entity-type, seed
  entity, valid_at).
- Pack the kept candidates into the doc-token budget.

This module is the **only** path that may touch the graph: Naive RAG
(``chat_retrieval_raw``) is forbidden from doing so.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from app.cohere_chat import ChatDocument
from app.filter_options_repo import summarize_workspace_graph
from app.graphiti_factory import graphiti_for_workspace

logger = logging.getLogger(__name__)


GRAPH_STRATEGY = "graph_graphiti_context_v1"

APPROX_CHARS_PER_TOKEN = 4


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    if isinstance(v, (list, tuple)):
        return [str(s).strip() for s in v if str(s).strip()]
    return []


def _parse_iso(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _temporally_overlaps(target: datetime, valid_from: Any, valid_to: Any) -> bool:
    vf = _parse_iso(valid_from)
    vt = _parse_iso(valid_to)
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    if vf and target < vf:
        return False
    if vt and target > vt:
        return False
    return True


def _render_graph_context_document(shape: dict[str, Any]) -> str:
    entity_total = int(shape.get("entity_total") or 0)
    edge_total = int(shape.get("edge_total") or 0)
    if entity_total <= 0:
        return ""

    lines: list[str] = []
    lines.append("Workspace graph (ground truth from the structured graph store):")
    lines.append(f"Total entities: {entity_total}")
    lines.append(f"Total relationships: {edge_total}")
    lines.append("Entity types:")
    for et in shape.get("entity_types") or []:
        name = str(et.get("name") or "Unknown")
        count = int(et.get("count") or 0)
        examples = [str(x) for x in (et.get("top_examples") or []) if x]
        truncated = bool(et.get("truncated_examples"))
        examples_str = ", ".join(examples) if examples else "(no named examples)"
        if truncated:
            shown = len(examples)
            lines.append(
                f"  - {name} (count={count}): {examples_str} "
                f"(showing first {shown} of {count})"
            )
        else:
            lines.append(f"  - {name} (count={count}): {examples_str}")
    edge_types = shape.get("edge_types") or []
    if edge_types:
        lines.append("Relationship types:")
        for et in edge_types:
            name = str(et.get("name") or "Unknown")
            count = int(et.get("count") or 0)
            lines.append(f"  - {name} (count={count})")
    lines.append(
        "When the user asks 'how many', 'list all', or otherwise asks "
        "about aggregates by type, treat the counts and example names "
        "above as authoritative. Use the fact snippets that follow only "
        "as supporting context."
    )
    return "\n".join(lines)


def _scope_check_for_entities(
    database_url: str,
    *,
    workspace_id: str,
    entity_ids: list[str],
    allowed_entity_types: set[str],
    allowed_document_ids: set[str],
    allowed_tags: set[str],
) -> bool:
    if not entity_ids:
        return False
    import psycopg

    with psycopg.connect(database_url) as conn:
        for eid in entity_ids:
            row = conn.execute(
                "SELECT type FROM entities WHERE id = %s::uuid LIMIT 1",
                (eid,),
            ).fetchone()
            if row is None:
                continue
            etype = row[0]
            if allowed_entity_types and etype not in allowed_entity_types:
                continue
            if allowed_document_ids:
                hit = conn.execute(
                    """
                    SELECT 1
                    FROM entity_episodes ee
                    JOIN episodes e ON e.id = ee.episode_id
                    WHERE ee.entity_id = %s::uuid
                      AND e.document_id = ANY(%s::uuid[])
                    LIMIT 1
                    """,
                    (eid, list(allowed_document_ids)),
                ).fetchone()
                if hit is None:
                    continue
            if allowed_tags:
                hit = conn.execute(
                    """
                    SELECT 1
                    FROM entity_notes en
                    JOIN atomic_notes n ON n.id = en.note_id
                    WHERE en.entity_id = %s::uuid
                      AND n.tags && %s::text[]
                    LIMIT 1
                    """,
                    (eid, list(allowed_tags)),
                ).fetchone()
                if hit is None:
                    continue
            return True
    return False


async def retrieve(
    settings: Any,
    database_url: str,
    *,
    workspace_id: str,
    query_text: str,
    scope: dict[str, Any],
    top_k: int,
    doc_token_budget: int,
) -> tuple[list[dict[str, Any]], list[ChatDocument], int, bool, str]:
    """Run Sprint 6's GraphRAG retrieval. Returns the same
    ``(retrieved_items, documents, total_candidates, truncated,
    strategy)`` tuple the dispatcher expects.
    """
    if not query_text.strip():
        return [], [], 0, False, GRAPH_STRATEGY

    # ---- Graph-context grounding document --------------------------------
    graph_context_doc: ChatDocument | None = None
    graph_context_item: dict[str, Any] | None = None
    try:
        shape = await asyncio.to_thread(
            summarize_workspace_graph,
            database_url,
            workspace_id=workspace_id,
            max_names_per_type=25,
        )
        rendered = _render_graph_context_document(shape)
        if rendered:
            graph_context_doc = ChatDocument(
                id="graph_context:workspace_shape",
                text=rendered,
                title="Workspace graph shape",
                metadata={"kind": "graph_context"},
            )
            graph_context_item = {
                "kind": "graph_context",
                "id": "workspace_shape",
                "type": "graph_context",
                "score": 1.0,
                "excerpt": rendered,
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "graph_retrieval_context_failed workspace=%s err=%s",
            workspace_id,
            type(exc).__name__,
        )

    # ---- Graphiti hybrid search ------------------------------------------
    try:
        graphiti = await graphiti_for_workspace(settings, workspace_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "graph_retrieval_graphiti_unavailable workspace=%s err=%s",
            workspace_id,
            type(exc).__name__,
        )
        return _finalize(
            [], [], 0, False, GRAPH_STRATEGY,
            graph_context_doc,
            graph_context_item,
        )

    try:
        edges = await graphiti.search(
            query=query_text, group_ids=[workspace_id], num_results=top_k
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "graph_retrieval_graphiti_search_failed err=%s",
            type(exc).__name__,
        )
        return _finalize(
            [], [], 0, False, GRAPH_STRATEGY,
            graph_context_doc,
            graph_context_item,
        )

    edges = list(edges or [])
    total_candidates = len(edges)
    truncated = total_candidates > top_k
    if truncated:
        edges = edges[:top_k]

    # ---- Scope filters ---------------------------------------------------
    allowed_entity_types = set(_str_list(scope.get("entity_types")))
    allowed_edge_types = set(_str_list(scope.get("edge_types")))
    allowed_document_ids = set(_str_list(scope.get("document_ids")))
    allowed_tags = set(_str_list(scope.get("tags")))
    valid_at = _parse_iso(scope.get("valid_at"))
    seed_entity_ids = set(_str_list(scope.get("seed_entity_ids")))

    candidate_rows: list[tuple[int, dict[str, Any]]] = []
    for edge in edges:
        fact = str(_attr(edge, "fact", "") or "").strip()
        if not fact:
            continue
        edge_type = str(_attr(edge, "name", "") or "RELATES_TO")
        if allowed_edge_types and edge_type not in allowed_edge_types:
            continue

        if valid_at is not None:
            edge_valid_from = _attr(edge, "valid_at")
            edge_valid_to = _attr(edge, "invalid_at")
            if not _temporally_overlaps(valid_at, edge_valid_from, edge_valid_to):
                continue

        edge_uuid = str(_attr(edge, "uuid", "") or "")
        rel_id_prefix = f"relationship:{edge_uuid}" if edge_uuid else None
        excerpt = fact[:1000]
        if not rel_id_prefix:
            continue

        candidate_rows.append(
            (
                len(excerpt),
                {
                    "kind": "relationship",
                    "id": edge_uuid,
                    "type": edge_type,
                    "score": float(_attr(edge, "score", 0.0) or 0.0),
                    "excerpt": excerpt,
                    "source_node_uuid": str(
                        _attr(edge, "source_node_uuid", "") or ""
                    ),
                    "target_node_uuid": str(
                        _attr(edge, "target_node_uuid", "") or ""
                    ),
                    "doc_id": rel_id_prefix,
                },
            )
        )

    candidate_rows.sort(key=lambda t: t[0])

    if (
        allowed_document_ids
        or allowed_tags
        or allowed_entity_types
        or seed_entity_ids
    ):
        from app import entities_repo  # local import to avoid cycles in tests

        for _size, row in candidate_rows:
            src_ent = await asyncio.to_thread(
                entities_repo.fetch_entity_id_for_graphiti_uuid,
                database_url,
                row["source_node_uuid"],
            )
            tgt_ent = await asyncio.to_thread(
                entities_repo.fetch_entity_id_for_graphiti_uuid,
                database_url,
                row["target_node_uuid"],
            )
            row["source_entity_id"] = src_ent
            row["target_entity_id"] = tgt_ent

            if seed_entity_ids:
                if (
                    src_ent not in seed_entity_ids
                    and tgt_ent not in seed_entity_ids
                ):
                    row["_skip"] = True
                    continue

            if allowed_entity_types or allowed_document_ids or allowed_tags:
                ok = await asyncio.to_thread(
                    _scope_check_for_entities,
                    database_url,
                    workspace_id=workspace_id,
                    entity_ids=[e for e in (src_ent, tgt_ent) if e],
                    allowed_entity_types=allowed_entity_types,
                    allowed_document_ids=allowed_document_ids,
                    allowed_tags=allowed_tags,
                )
                if not ok:
                    row["_skip"] = True

    # ---- Pack into budget ------------------------------------------------
    retrieved_items: list[dict[str, Any]] = []
    documents: list[ChatDocument] = []
    budget_chars = doc_token_budget * APPROX_CHARS_PER_TOKEN
    used_chars = 0
    if graph_context_doc is not None:
        used_chars += len(graph_context_doc.text)

    for _size, row in candidate_rows:
        if row.get("_skip"):
            continue
        excerpt = row["excerpt"]
        if used_chars + len(excerpt) > budget_chars and documents:
            truncated = True
            break
        used_chars += len(excerpt)
        retrieved_items.append(
            {
                "kind": row["kind"],
                "id": row["id"],
                "type": row.get("type"),
                "score": row.get("score"),
                "excerpt": excerpt,
                "source_entity_id": row.get("source_entity_id"),
                "target_entity_id": row.get("target_entity_id"),
            }
        )
        documents.append(
            ChatDocument(
                id=row["doc_id"],
                text=excerpt,
                title=row.get("type"),
                metadata={
                    "kind": row["kind"],
                    "score": str(row.get("score") or 0.0),
                },
            )
        )

    return _finalize(
        retrieved_items,
        documents,
        total_candidates,
        truncated,
        GRAPH_STRATEGY,
        graph_context_doc,
        graph_context_item,
    )


def _finalize(
    retrieved_items: list[dict[str, Any]],
    documents: list[ChatDocument],
    total_candidates: int,
    truncated: bool,
    strategy: str,
    graph_context_doc: ChatDocument | None,
    graph_context_item: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[ChatDocument], int, bool, str]:
    if graph_context_doc is not None and graph_context_item is not None:
        documents.insert(0, graph_context_doc)
        retrieved_items.insert(0, graph_context_item)
    return retrieved_items, documents, total_candidates, truncated, strategy
