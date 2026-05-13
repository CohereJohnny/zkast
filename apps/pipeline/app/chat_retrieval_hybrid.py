"""Sprint 6b / TD-015 — hybrid retrieval: traversal + supporting evidence.

Hybrid mode is what "real" GraphRAG looks like in this codebase:

1. Classify the query intent.
2. Dispatch to the typed-entity or path traversal handler when the
   intent matches and slot extraction succeeded.
3. Always also pull the supporting evidence from the standard
   ``chat_retrieval_graph`` path so the LLM has both the deterministic
   answer and the surrounding facts.

Returned strategy strings let the eval and UI distinguish between
turns that exercised a deterministic handler vs the fallback graph
path:

- ``hybrid_typed_entity_v1`` — typed aggregation handler fired.
- ``hybrid_path_v1`` — path traversal handler fired.
- ``hybrid_vector_v1`` — no handler fired; the graph-strategy
  documents are what the LLM saw.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app import chat_handler_path, chat_handler_typed, chat_intent
from app.chat_retrieval_graph import retrieve as graph_retrieve
from app.cohere_chat import ChatDocument

logger = logging.getLogger(__name__)


HYBRID_TYPED_STRATEGY = "hybrid_typed_entity_v1"
HYBRID_PATH_STRATEGY = "hybrid_path_v1"
HYBRID_VECTOR_STRATEGY = "hybrid_vector_v1"


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
    """Run hybrid retrieval. The deterministic handler's output (if any)
    is prepended ahead of the graph-strategy supporting evidence so the
    LLM treats it as the primary grounding."""
    if not query_text.strip():
        return [], [], 0, False, HYBRID_VECTOR_STRATEGY

    # ---- Intent + handler dispatch --------------------------------------
    try:
        intent = await asyncio.to_thread(
            chat_intent.classify,
            database_url,
            workspace_id=workspace_id,
            query_text=query_text,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "hybrid_intent_classify_failed workspace=%s err=%s",
            workspace_id,
            type(exc).__name__,
        )
        intent = chat_intent.IntentClassification(
            kind="vector", slots=chat_intent.IntentSlots()
        )

    handler_items: list[dict[str, Any]] = []
    handler_docs: list[ChatDocument] = []
    chosen_strategy = HYBRID_VECTOR_STRATEGY

    if intent.is_aggregation():
        try:
            handler_items, handler_docs = await asyncio.to_thread(
                chat_handler_typed.answer,
                database_url,
                workspace_id=workspace_id,
                intent=intent,
            )
            if handler_docs:
                chosen_strategy = HYBRID_TYPED_STRATEGY
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "hybrid_typed_handler_failed workspace=%s err=%s",
                workspace_id,
                type(exc).__name__,
            )

    elif intent.is_multi_hop():
        try:
            handler_items, handler_docs = await asyncio.to_thread(
                chat_handler_path.answer,
                database_url,
                workspace_id=workspace_id,
                intent=intent,
            )
            if handler_docs:
                chosen_strategy = HYBRID_PATH_STRATEGY
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "hybrid_path_handler_failed workspace=%s err=%s",
                workspace_id,
                type(exc).__name__,
            )

    # ---- Always-attached graph-strategy supporting evidence -------------
    (
        graph_items,
        graph_docs,
        graph_total,
        graph_truncated,
        _graph_strategy,
    ) = await graph_retrieve(
        settings,
        database_url,
        workspace_id=workspace_id,
        query_text=query_text,
        scope=scope,
        top_k=top_k,
        doc_token_budget=doc_token_budget,
    )

    # Compose: deterministic handler answer first, then graph evidence.
    items: list[dict[str, Any]] = list(handler_items) + list(graph_items)
    docs: list[ChatDocument] = list(handler_docs) + list(graph_docs)

    return (
        items,
        docs,
        graph_total + len(handler_items),
        graph_truncated,
        chosen_strategy,
    )
