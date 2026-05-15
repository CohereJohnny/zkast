"""Embed atomic notes into ``retrieval_embeddings`` (Zettel vs A-MEM slices)."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.cohere_adapters import CohereEmbedder
from app.notes_repo import fetch_note
from app.retrieval_embeddings_repo import (
    INDEX_KIND_NOTE_AMEM,
    INDEX_KIND_NOTE_ZETTEL,
    upsert_embedding,
)

logger = structlog.get_logger(__name__)


def _zettel_text(note: dict[str, Any]) -> str:
    return f"{note.get('title') or ''}\n{note.get('body') or ''}".strip()[:8000]


def _amem_text(note: dict[str, Any]) -> str:
    kws = note.get("memory_keywords") or []
    kw_line = ", ".join(str(k) for k in kws if k)[:2000]
    ctx = str(note.get("memory_context") or "").strip()[:2000]
    base = _zettel_text(note)
    parts = [base]
    if ctx:
        parts.append(f"memory_context: {ctx}")
    if kw_line:
        parts.append(f"memory_keywords: {kw_line}")
    return "\n".join(parts).strip()[:12000]


async def upsert_zettel_embeddings_for_notes(
    *,
    api_key: str,
    database_url: str,
    workspace_id: str,
    note_ids: list[str],
    agent_id: str | None,
    embed_model: str,
    embedding_dim: int = 1536,
) -> None:
    if not note_ids:
        return
    embedder = CohereEmbedder(api_key=api_key, model=embed_model, embedding_dim=embedding_dim)
    pairs: list[tuple[str, str]] = []
    for nid in note_ids:
        n = await asyncio.to_thread(fetch_note, database_url, workspace_id=workspace_id, note_id=nid)
        if not n:
            continue
        text = _zettel_text(n)
        if not text:
            continue
        pairs.append((nid, text))
    if not pairs:
        return
    try:
        vectors = await embedder.create_batch([p[1] for p in pairs])
    except Exception as exc:  # noqa: BLE001
        logger.warning("note_zettel_embed_batch_failed", error=str(exc))
        return
    aid = str(agent_id).strip() if agent_id else None
    for (nid, text), vec in zip(pairs, vectors, strict=False):
        if not vec:
            continue
        await asyncio.to_thread(
            upsert_embedding,
            database_url,
            workspace_id=workspace_id,
            index_kind=INDEX_KIND_NOTE_ZETTEL,
            source_kind="atomic_note",
            source_id=nid,
            text=text[:12000],
            embedding=list(vec),
            document_id=None,
            embedding_model=embed_model,
            embedding_dim=embedding_dim,
            attributes={"note_id": nid},
            agent_id=aid,
        )


async def upsert_amem_embeddings_for_notes(
    *,
    api_key: str,
    database_url: str,
    workspace_id: str,
    note_ids: list[str],
    agent_id: str | None,
    embed_model: str,
    embedding_dim: int = 1536,
) -> None:
    if not note_ids:
        return
    embedder = CohereEmbedder(api_key=api_key, model=embed_model, embedding_dim=embedding_dim)
    pairs: list[tuple[str, str]] = []
    for nid in note_ids:
        n = await asyncio.to_thread(fetch_note, database_url, workspace_id=workspace_id, note_id=nid)
        if not n:
            continue
        text = _amem_text(n)
        if not text:
            continue
        pairs.append((nid, text))
    if not pairs:
        return
    try:
        vectors = await embedder.create_batch([p[1] for p in pairs])
    except Exception as exc:  # noqa: BLE001
        logger.warning("note_amem_embed_batch_failed", error=str(exc))
        return
    aid = str(agent_id).strip() if agent_id else None
    for (nid, text), vec in zip(pairs, vectors, strict=False):
        if not vec:
            continue
        await asyncio.to_thread(
            upsert_embedding,
            database_url,
            workspace_id=workspace_id,
            index_kind=INDEX_KIND_NOTE_AMEM,
            source_kind="atomic_note",
            source_id=nid,
            text=text[:12000],
            embedding=list(vec),
            document_id=None,
            embedding_model=embed_model,
            embedding_dim=embedding_dim,
            attributes={"note_id": nid},
            agent_id=aid,
        )
