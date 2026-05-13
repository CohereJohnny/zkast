"""Sprint 6b / TD-015 — typed-entity aggregation handler.

Answers "how many X", "list all Y", "count Z by type" style queries
**deterministically** by running structured SELECTs against the
typed ``entities`` table rather than relying on a vector ranker.

Output shape: a single ``ChatDocument`` per matched type with the
authoritative count and the full list of canonical names (capped at
500 names to keep the document inside the per-turn token budget).
Plus retrieved-item records the eval / retrieval-inspector can
display.

This handler is reached only when:
1. The chat ``retrieval_mode`` is ``hybrid``.
2. The intent router (``chat_intent.classify``) returned ``aggregation``.

If the intent says aggregation but no entity types were extracted, the
handler returns an empty result so the hybrid strategy falls back to
the graph retrieval path (which still has the graph-context grounding
document).
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.chat_intent import IntentClassification
from app.cohere_chat import ChatDocument

logger = logging.getLogger(__name__)


TYPED_STRATEGY = "hybrid_typed_entity_v1"


def _list_entities_of_types(
    database_url: str,
    *,
    workspace_id: str,
    entity_types: list[str],
    name_limit_per_type: int = 500,
) -> dict[str, list[str]]:
    """Return ``{type: [canonical_names...]}`` for each requested type."""
    if not entity_types:
        return {}
    out: dict[str, list[str]] = {}
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        for t in entity_types:
            rows = conn.execute(
                """
                SELECT canonical_name
                FROM entities
                WHERE workspace_id = %s::uuid AND type = %s
                ORDER BY canonical_name ASC
                LIMIT %s
                """,
                (workspace_id, t, int(name_limit_per_type)),
            ).fetchall()
            names = [str(r["canonical_name"]) for r in rows if r.get("canonical_name")]
            out[t] = names
    return out


def _count_entities_by_type(
    database_url: str,
    *,
    workspace_id: str,
    entity_types: list[str],
) -> dict[str, int]:
    if not entity_types:
        return {}
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT type, COUNT(*) AS c
            FROM entities
            WHERE workspace_id = %s::uuid AND type = ANY(%s::text[])
            GROUP BY type
            """,
            (workspace_id, entity_types),
        ).fetchall()
    return {str(r["type"]): int(r["c"]) for r in rows}


def _render_document(counts: dict[str, int], lists: dict[str, list[str]]) -> str:
    lines: list[str] = [
        "Workspace typed-entity ground truth (deterministic, from the structured graph store):"
    ]
    for t, c in counts.items():
        names = lists.get(t) or []
        if not names:
            lines.append(f"  - {t}: count={c} (no named entities indexed)")
            continue
        if c <= 500 and len(names) >= c:
            joined = ", ".join(names)
            lines.append(f"  - {t}: count={c}. All names: {joined}")
        else:
            shown = ", ".join(names)
            lines.append(
                f"  - {t}: count={c}. Showing {len(names)} of {c} names: {shown}"
            )
    lines.append(
        "These counts are authoritative. Answer the user's question using "
        "these numbers and names; the supplementary graph snippets below "
        "are for context only."
    )
    return "\n".join(lines)


def answer(
    database_url: str,
    *,
    workspace_id: str,
    intent: IntentClassification,
) -> tuple[list[dict[str, Any]], list[ChatDocument]]:
    """Return ``(retrieved_items, documents)`` for the typed-entity
    aggregation answer. Empty when no entity types were extracted.
    """
    types = intent.slots.entity_types
    if not types:
        return [], []

    counts = _count_entities_by_type(
        database_url, workspace_id=workspace_id, entity_types=types
    )
    lists = _list_entities_of_types(
        database_url, workspace_id=workspace_id, entity_types=types
    )
    if not counts and not lists:
        return [], []

    text = _render_document(counts, lists)
    doc = ChatDocument(
        id="typed_entity:aggregation",
        text=text,
        title="Typed-entity aggregation",
        metadata={"kind": "typed_entity", "types": ",".join(types)},
    )
    item = {
        "kind": "typed_entity",
        "id": "aggregation",
        "type": ",".join(types),
        "score": 1.0,
        "excerpt": text[:2000],
        "counts": counts,
        "names": lists,
    }
    return [item], [doc]
