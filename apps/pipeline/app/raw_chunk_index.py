"""Sprint 6b — Naive-RAG raw-chunk index management.

The Naive-RAG baseline retrieves directly from the parsed PDF chunks
(``episodes`` rows of ``kind='pdf_chunk'``). It must NOT touch
zettelkasten atomic notes, extracted entities, relationships, the
graph-context grounding document, Graphiti, or graph traversal — that
is the whole point of having an honest baseline.

This module covers:

- ``backfill_raw_chunks(workspace_id)`` — embed every PDF chunk
  episode for a workspace and upsert into ``retrieval_embeddings``
  with ``index_kind='raw_chunk'``. Safe to re-run; idempotent via
  the unique constraint ``(workspace_id, index_kind, source_id)``.
- ``count_raw_chunks(workspace_id)`` — return ``{episodes_total,
  embeddings_total, missing}`` so the UI can tell the user "Naive
  RAG index is N/M ready".

Backfill is async-friendly via ``asyncio.to_thread`` from the chat
turn / internal admin route.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.cohere_adapters import CohereEmbedder
from app.retrieval_embeddings_repo import (
    INDEX_KIND_RAW_CHUNK,
    list_existing_source_ids,
    upsert_embedding,
)

logger = logging.getLogger(__name__)

# Batch size for Cohere embed calls. The endpoint accepts up to 96 input
# strings per request as of embed-v4.0; we use 32 to keep per-call
# latency predictable and to leave headroom for the existing ingestion
# embed traffic when both run concurrently.
EMBED_BATCH_SIZE = 32

# Max characters per chunk we send to Cohere. PDF chunks already average
# ~1500 chars; this is a safety cap so a degenerate one-page document
# can't blow the 512-token embed input window.
CHUNK_TEXT_MAX_CHARS = 6_000


def _list_raw_chunks(
    database_url: str,
    *,
    workspace_id: str,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
                e.id::text AS id,
                e.document_id::text AS document_id,
                e.text,
                e.page_start,
                e.page_end,
                e.sequence,
                e.agent_id::text AS agent_id
            FROM episodes e
            WHERE e.workspace_id = %s::uuid
              AND e.kind IN (
                'pdf_chunk',
                'text_chunk',
                'markdown_chunk',
                'email_chunk',
                'north_message',
                'north_turn_window',
                'north_tool_event'
              )
              AND e.text IS NOT NULL
              AND length(trim(e.text)) > 0
            ORDER BY e.document_id, e.sequence
            """,
            (workspace_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_raw_chunks(
    database_url: str,
    *,
    workspace_id: str,
) -> dict[str, int]:
    """Return ``{episodes_total, embeddings_total, missing}`` so callers
    can decide whether to trigger a backfill."""
    chunks = _list_raw_chunks(database_url, workspace_id=workspace_id)
    have = list_existing_source_ids(
        database_url,
        workspace_id=workspace_id,
        index_kind=INDEX_KIND_RAW_CHUNK,
    )
    episodes_total = len(chunks)
    embeddings_total = len(have)
    missing = sum(1 for c in chunks if c["id"] not in have)
    return {
        "episodes_total": episodes_total,
        "embeddings_total": embeddings_total,
        "missing": missing,
    }


async def backfill_raw_chunks(
    database_url: str,
    *,
    workspace_id: str,
    api_key: str,
    embedding_model: str = "embed-v4.0",
    embedding_dim: int = 1536,
    on_progress: Any | None = None,
) -> dict[str, int]:
    """Embed every PDF chunk episode that does not yet have a Naive-RAG
    embedding row and upsert it.

    Idempotent: only chunks whose ``episodes.id`` is not in the existing
    ``retrieval_embeddings`` table are embedded. Returns a summary
    ``{processed, skipped, errors}`` that the caller can surface to the
    UI / drawer.

    ``on_progress`` is an optional callback ``(processed, total)`` that
    fires after each Cohere batch — wired by the eval runner / internal
    route so users see progress for big workspaces.
    """
    chunks = _list_raw_chunks(database_url, workspace_id=workspace_id)
    if not chunks:
        return {"processed": 0, "skipped": 0, "errors": 0, "total": 0}

    have = list_existing_source_ids(
        database_url,
        workspace_id=workspace_id,
        index_kind=INDEX_KIND_RAW_CHUNK,
    )
    pending = [c for c in chunks if c["id"] not in have]
    total = len(chunks)
    if not pending:
        return {
            "processed": 0,
            "skipped": total,
            "errors": 0,
            "total": total,
        }

    embedder = CohereEmbedder(
        api_key=api_key,
        model=embedding_model,
        embedding_dim=embedding_dim,
    )

    processed = 0
    errors = 0
    for i in range(0, len(pending), EMBED_BATCH_SIZE):
        batch = pending[i : i + EMBED_BATCH_SIZE]
        texts = [c["text"][:CHUNK_TEXT_MAX_CHARS] for c in batch]
        try:
            vectors = await embedder.create_batch(texts)
        except Exception as exc:  # noqa: BLE001
            errors += len(batch)
            logger.warning(
                "raw_chunk_backfill_batch_failed workspace=%s err=%s",
                workspace_id,
                type(exc).__name__,
            )
            continue

        for chunk, vec in zip(batch, vectors):
            if not vec:
                errors += 1
                continue
            try:
                upsert_embedding(
                    database_url,
                    workspace_id=workspace_id,
                    index_kind=INDEX_KIND_RAW_CHUNK,
                    source_kind="episode_chunk",
                    source_id=str(chunk["id"]),
                    text=chunk["text"][:CHUNK_TEXT_MAX_CHARS],
                    embedding=list(vec),
                    document_id=str(chunk["document_id"]),
                    page_start=chunk.get("page_start"),
                    page_end=chunk.get("page_end"),
                    chunk_sequence=chunk.get("sequence"),
                    embedding_model=embedding_model,
                    embedding_dim=embedding_dim,
                    attributes={"agent_id": chunk["agent_id"]} if chunk.get("agent_id") else {},
                    agent_id=chunk.get("agent_id"),
                )
                processed += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logger.warning(
                    "raw_chunk_backfill_upsert_failed chunk=%s err=%s",
                    chunk["id"],
                    type(exc).__name__,
                )

        if on_progress is not None:
            try:
                await on_progress(processed, len(pending))
            except Exception:  # noqa: BLE001
                pass

    skipped = total - len(pending)
    return {
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "total": total,
    }


async def embed_query(
    *,
    api_key: str,
    query_text: str,
    model: str = "embed-v4.0",
    embedding_dim: int = 1536,
) -> list[float]:
    """Embed a single query string for retrieval.

    Uses Cohere ``embed`` with ``input_type='search_document'`` by way of
    ``CohereEmbedder.create`` for now. Phase 2 follow-up: pass
    ``input_type='search_query'`` directly to Cohere — this is a known
    deferred item flagged in Sprint 6b notes.
    """
    embedder = CohereEmbedder(
        api_key=api_key, model=model, embedding_dim=embedding_dim
    )
    return await embedder.create(query_text)
