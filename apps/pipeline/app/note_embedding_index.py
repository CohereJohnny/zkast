"""Embed atomic notes into ``retrieval_embeddings`` (Zettel vs A-MEM slices)."""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row

from app.cohere_adapters import CohereEmbedder
from app.notes_repo import fetch_note
from app.retrieval_embeddings_repo import (
    INDEX_KIND_NOTE_AMEM,
    INDEX_KIND_NOTE_ZETTEL,
    list_existing_source_ids,
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


def _note_has_amem_fields(note: dict[str, Any]) -> bool:
    kws = note.get("memory_keywords") or []
    ctx = str(note.get("memory_context") or "").strip()
    return bool(ctx or kws)


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


async def backfill_note_embeddings(
    *,
    api_key: str,
    database_url: str,
    workspace_id: str,
    embed_model: str = "embed-v4.0",
    embedding_dim: int = 1536,
    kinds: list[str] | None = None,
    agent_id: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Backfill ``note_zettel`` and/or ``note_amem`` rows for workspace notes."""
    want = set(kinds or [INDEX_KIND_NOTE_ZETTEL, INDEX_KIND_NOTE_AMEM])
    valid = {INDEX_KIND_NOTE_ZETTEL, INDEX_KIND_NOTE_AMEM}
    want &= valid
    if not want:
        return {"embedded": {}, "skipped": 0, "candidates": 0}

    where = ["n.workspace_id = %s::uuid"]
    params: list[Any] = [workspace_id]
    if agent_id:
        where.append("n.agent_id = %s::uuid")
        params.append(agent_id)
    where_sql = " AND ".join(where)

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            f"""
            SELECT n.id::text AS id, n.agent_id::text AS agent_id,
                   n.title, n.body, n.memory_context, n.memory_keywords
            FROM atomic_notes n
            WHERE {where_sql}
            ORDER BY n.updated_at DESC
            LIMIT %s
            """,
            [*params, max(1, min(limit, 5000))],
        ).fetchall()

    candidates = [dict(r) for r in rows]
    embedded: dict[str, int] = {k: 0 for k in want}
    skipped = 0

    zettel_indexed = await asyncio.to_thread(
        list_existing_source_ids,
        database_url,
        workspace_id=workspace_id,
        index_kind=INDEX_KIND_NOTE_ZETTEL,
    )
    amem_indexed = await asyncio.to_thread(
        list_existing_source_ids,
        database_url,
        workspace_id=workspace_id,
        index_kind=INDEX_KIND_NOTE_AMEM,
    )

    for row in candidates:
        nid = row["id"]
        aid = str(row["agent_id"]).strip() if row.get("agent_id") else None
        note = {
            "title": row.get("title"),
            "body": row.get("body"),
            "memory_context": row.get("memory_context"),
            "memory_keywords": row.get("memory_keywords"),
        }
        if INDEX_KIND_NOTE_ZETTEL in want and nid not in zettel_indexed:
            await upsert_zettel_embeddings_for_notes(
                api_key=api_key,
                database_url=database_url,
                workspace_id=workspace_id,
                note_ids=[nid],
                agent_id=aid,
                embed_model=embed_model,
                embedding_dim=embedding_dim,
            )
            embedded[INDEX_KIND_NOTE_ZETTEL] += 1
        elif INDEX_KIND_NOTE_ZETTEL in want:
            skipped += 1

        if INDEX_KIND_NOTE_AMEM in want and _note_has_amem_fields(note):
            if nid not in amem_indexed:
                await upsert_amem_embeddings_for_notes(
                    api_key=api_key,
                    database_url=database_url,
                    workspace_id=workspace_id,
                    note_ids=[nid],
                    agent_id=aid,
                    embed_model=embed_model,
                    embedding_dim=embedding_dim,
                )
                embedded[INDEX_KIND_NOTE_AMEM] += 1
            else:
                skipped += 1

    return {
        "embedded": embedded,
        "skipped": skipped,
        "candidates": len(candidates),
        "agent_id": agent_id,
    }
