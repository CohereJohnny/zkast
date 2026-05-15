"""Vector retrieval over embedded atomic notes (Zettel vs A-MEM text slices)."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.cohere_chat import ChatDocument
from app.graphiti_factory import resolve_cohere_api_key
from app.raw_chunk_index import embed_query
from app.retrieval_embeddings_repo import (
    INDEX_KIND_NOTE_AMEM,
    INDEX_KIND_NOTE_ZETTEL,
    search_by_kind,
)

logger = structlog.get_logger(__name__)

STRATEGY_ZETTEL = "notes_vector_zettel_v1"
STRATEGY_AMEM = "notes_vector_amem_v1"

APPROX_CHARS_PER_TOKEN = 4


async def _retrieve(
    settings: Any,
    database_url: str,
    *,
    workspace_id: str,
    query_text: str,
    scope: dict[str, Any],
    top_k: int,
    doc_token_budget: int,
    index_kind: str,
    strategy: str,
    hit_kind: str,
) -> tuple[list[dict[str, Any]], list[ChatDocument], int, bool, str]:
    if not query_text.strip():
        return [], [], 0, False, strategy

    api_key = await asyncio.to_thread(resolve_cohere_api_key, settings, workspace_id)
    if not api_key:
        logger.warning("notes_vector_no_api_key", workspace_id=workspace_id, index_kind=index_kind)
        return [], [], 0, False, strategy

    try:
        vec = await embed_query(api_key=api_key, query_text=query_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "notes_vector_embed_failed",
            workspace_id=workspace_id,
            index_kind=index_kind,
            error=type(exc).__name__,
        )
        return [], [], 0, False, strategy

    agent_id = str(scope.get("agent_id")).strip() if scope.get("agent_id") else None

    try:
        hits = await asyncio.to_thread(
            search_by_kind,
            database_url,
            workspace_id=workspace_id,
            index_kind=index_kind,
            query_embedding=vec,
            top_k=top_k,
            document_id=None,
            agent_id=agent_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "notes_vector_search_failed",
            workspace_id=workspace_id,
            index_kind=index_kind,
            error=type(exc).__name__,
        )
        return [], [], 0, False, strategy

    total_candidates = len(hits)
    truncated = False
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
        sid = h["source_id"]
        doc_id_prefix = f"{hit_kind}:{sid}"
        retrieved_items.append(
            {
                "kind": hit_kind,
                "id": sid,
                "type": "atomic_note",
                "score": h.get("score"),
                "excerpt": excerpt,
                "document_id": h.get("document_id"),
            }
        )
        documents.append(
            ChatDocument(
                id=doc_id_prefix,
                text=excerpt,
                title="Atomic note",
                metadata={
                    "kind": hit_kind,
                    "score": str(h.get("score") or 0.0),
                },
            )
        )

    return retrieved_items, documents, total_candidates, truncated, strategy


async def retrieve_zettel(
    settings: Any,
    database_url: str,
    *,
    workspace_id: str,
    query_text: str,
    scope: dict[str, Any],
    top_k: int,
    doc_token_budget: int,
) -> tuple[list[dict[str, Any]], list[ChatDocument], int, bool, str]:
    return await _retrieve(
        settings,
        database_url,
        workspace_id=workspace_id,
        query_text=query_text,
        scope=scope,
        top_k=top_k,
        doc_token_budget=doc_token_budget,
        index_kind=INDEX_KIND_NOTE_ZETTEL,
        strategy=STRATEGY_ZETTEL,
        hit_kind="note_zettel",
    )


async def retrieve_amem(
    settings: Any,
    database_url: str,
    *,
    workspace_id: str,
    query_text: str,
    scope: dict[str, Any],
    top_k: int,
    doc_token_budget: int,
) -> tuple[list[dict[str, Any]], list[ChatDocument], int, bool, str]:
    return await _retrieve(
        settings,
        database_url,
        workspace_id=workspace_id,
        query_text=query_text,
        scope=scope,
        top_k=top_k,
        doc_token_budget=doc_token_budget,
        index_kind=INDEX_KIND_NOTE_AMEM,
        strategy=STRATEGY_AMEM,
        hit_kind="note_amem",
    )
