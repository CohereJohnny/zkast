"""Sprint 6b — Naive RAG retrieval over raw parsed document chunks.

This strategy is the **control arm** in the GraphRAG-vs-Naive-RAG eval.
Hard rules, enforced by both code and tests:

- Only ``retrieval_embeddings`` rows with ``index_kind = 'raw_chunk'``
  are visible.
- No queries to ``atomic_notes``, ``entities``, ``relationships``,
  Graphiti, or any graph traversal.
- No graph-context grounding document.

Implementation note: the embedding index for ``raw_chunk`` is
populated by ``raw_chunk_index.backfill_raw_chunks``. If it is empty
for a workspace, this strategy returns no documents and the chat turn
falls through to the standard refusal path.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.cohere_chat import ChatDocument
from app.graphiti_factory import resolve_cohere_api_key
from app.raw_chunk_index import embed_query
from app.retrieval_embeddings_repo import (
    INDEX_KIND_RAW_CHUNK,
    search_by_kind,
)

logger = structlog.get_logger(__name__)


RAW_CHUNK_STRATEGY = "rag_raw_chunk_v1"


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
    """Run a Naive-RAG retrieval.

    Returns ``(retrieved_items, documents, total_candidates,
    truncated, retrieval_strategy)`` to match the shape ``chat_turn``
    expects from any strategy.

    The Naive-RAG baseline intentionally ignores most of the chat scope
    (entity types, edge types, seed entities, tags) because those are
    graph concepts the Naive baseline cannot use without cheating. The
    one scope filter we honour is ``document_ids[0]`` — the user
    legitimately may want to restrict the baseline to a single document.
    """
    if not query_text.strip():
        return [], [], 0, False, RAW_CHUNK_STRATEGY

    api_key = await asyncio.to_thread(
        resolve_cohere_api_key, settings, workspace_id
    )
    if not api_key:
        logger.warning(
            "raw_rag_no_api_key", workspace_id=workspace_id
        )
        return [], [], 0, False, RAW_CHUNK_STRATEGY

    try:
        vec = await embed_query(api_key=api_key, query_text=query_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "raw_rag_embed_failed",
            workspace_id=workspace_id,
            error=type(exc).__name__,
        )
        return [], [], 0, False, RAW_CHUNK_STRATEGY

    document_filter: str | None = None
    doc_ids = scope.get("document_ids") or []
    if isinstance(doc_ids, list) and doc_ids:
        document_filter = str(doc_ids[0])
    elif isinstance(doc_ids, str) and doc_ids.strip():
        document_filter = doc_ids.split(",")[0].strip() or None

    try:
        hits = await asyncio.to_thread(
            search_by_kind,
            database_url,
            workspace_id=workspace_id,
            index_kind=INDEX_KIND_RAW_CHUNK,
            query_embedding=vec,
            top_k=top_k,
            document_id=document_filter,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "raw_rag_search_failed",
            workspace_id=workspace_id,
            error=type(exc).__name__,
        )
        return [], [], 0, False, RAW_CHUNK_STRATEGY

    total_candidates = len(hits)
    truncated = False

    # Pack documents into the doc-token budget. Chars-per-token heuristic
    # mirrors ``chat_turn._retrieve``.
    APPROX_CHARS_PER_TOKEN = 4
    budget_chars = doc_token_budget * APPROX_CHARS_PER_TOKEN
    used_chars = 0

    retrieved_items: list[dict[str, Any]] = []
    documents: list[ChatDocument] = []
    for h in hits:
        excerpt = (h.get("text") or "")[:2000]
        if not excerpt.strip():
            continue
        if used_chars + len(excerpt) > budget_chars and documents:
            truncated = True
            break
        used_chars += len(excerpt)

        doc_id_prefix = f"raw_chunk:{h['source_id']}"
        retrieved_items.append(
            {
                "kind": "raw_chunk",
                "id": h["source_id"],
                "type": "pdf_chunk",
                "score": h.get("score"),
                "excerpt": excerpt,
                "document_id": h.get("document_id"),
                "page_start": h.get("page_start"),
                "page_end": h.get("page_end"),
                "chunk_sequence": h.get("chunk_sequence"),
            }
        )
        documents.append(
            ChatDocument(
                id=doc_id_prefix,
                text=excerpt,
                title=(
                    f"Document chunk p.{h.get('page_start')}"
                    if h.get("page_start") is not None
                    else "Document chunk"
                ),
                metadata={
                    "kind": "raw_chunk",
                    "document_id": str(h.get("document_id") or ""),
                    "page_start": str(h.get("page_start") or ""),
                    "page_end": str(h.get("page_end") or ""),
                    "score": str(h.get("score") or 0.0),
                },
            )
        )

    return retrieved_items, documents, total_candidates, truncated, RAW_CHUNK_STRATEGY
