"""Sprint 6b — Postgres repo for the ``retrieval_embeddings`` index.

The table is a shared physical store keyed by an ``index_kind``
discriminator so we can keep Naive RAG (``raw_chunk``) strictly
separate from graph artifacts (``atomic_note``, ``entity``,
``relationship``, ``graph_context``) — see migration
[`0010_retrieval_eval_indexes`](../../migrations/alembic/versions/0010_retrieval_eval_indexes.py)
and the design note in [techstack.md](../../../specs/techstack.md)
"Retrieval modes for Sprint 6b evaluation".

Sync psycopg style matches the other ``apps/pipeline/app/*_repo.py``
modules so it can be wrapped in ``asyncio.to_thread``. The pgvector
adapter is registered per-connection.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Json


# Allowed ``index_kind`` values mirror the CHECK constraint in
# migration 0010. Keep these literals in sync with the SQL.
INDEX_KIND_RAW_CHUNK = "raw_chunk"
INDEX_KIND_ATOMIC_NOTE = "atomic_note"
INDEX_KIND_ENTITY = "entity"
INDEX_KIND_RELATIONSHIP = "relationship"
INDEX_KIND_GRAPH_CONTEXT = "graph_context"
INDEX_KIND_NOTE_ZETTEL = "note_zettel"
INDEX_KIND_NOTE_AMEM = "note_amem"

VALID_INDEX_KINDS = {
    INDEX_KIND_RAW_CHUNK,
    INDEX_KIND_ATOMIC_NOTE,
    INDEX_KIND_ENTITY,
    INDEX_KIND_RELATIONSHIP,
    INDEX_KIND_GRAPH_CONTEXT,
    INDEX_KIND_NOTE_ZETTEL,
    INDEX_KIND_NOTE_AMEM,
}


def _connect(database_url: str) -> psycopg.Connection:
    """Open a connection with the pgvector adapter pre-registered.

    Centralizing this keeps every callsite from re-importing
    ``pgvector.psycopg`` and missing the registration step (which
    silently corrupts vector binding).
    """
    conn = psycopg.connect(database_url, row_factory=dict_row)
    try:
        register_vector(conn)
    except Exception:
        conn.close()
        raise
    return conn


def upsert_embedding(
    database_url: str,
    *,
    workspace_id: str,
    index_kind: str,
    source_kind: str,
    source_id: str,
    text: str,
    embedding: list[float],
    document_id: str | None = None,
    page_start: int | None = None,
    page_end: int | None = None,
    chunk_sequence: int | None = None,
    embedding_model: str = "embed-v4.0",
    embedding_dim: int = 1536,
    attributes: dict[str, Any] | None = None,
    agent_id: str | None = None,
) -> str:
    """Insert-or-update a single embedding row keyed by
    ``(workspace_id, index_kind, source_id)``.

    Returns the row id (existing or new). Used by the raw-chunk
    backfill task and by future ``atomic_note`` / ``entity`` backfills.
    """
    if index_kind not in VALID_INDEX_KINDS:
        raise ValueError(f"unknown index_kind: {index_kind!r}")

    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO retrieval_embeddings (
                    id, workspace_id, index_kind, source_kind, source_id,
                    document_id, page_start, page_end, chunk_sequence,
                    text, embedding, embedding_model, embedding_dim,
                    attributes, agent_id
                )
                VALUES (
                    %s::uuid, %s::uuid, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s::uuid
                )
                ON CONFLICT (workspace_id, index_kind, source_id)
                DO UPDATE SET
                    source_kind = EXCLUDED.source_kind,
                    document_id = EXCLUDED.document_id,
                    page_start = EXCLUDED.page_start,
                    page_end = EXCLUDED.page_end,
                    chunk_sequence = EXCLUDED.chunk_sequence,
                    text = EXCLUDED.text,
                    embedding = EXCLUDED.embedding,
                    embedding_model = EXCLUDED.embedding_model,
                    embedding_dim = EXCLUDED.embedding_dim,
                    attributes = EXCLUDED.attributes,
                    agent_id = EXCLUDED.agent_id,
                    updated_at = now()
                RETURNING id::text AS id
                """,
                (
                    str(uuid4()),
                    workspace_id,
                    index_kind,
                    source_kind,
                    source_id,
                    document_id,
                    page_start,
                    page_end,
                    chunk_sequence,
                    text,
                    embedding,
                    embedding_model,
                    embedding_dim,
                    Json(attributes or {}),
                    agent_id,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            assert row is not None
            return row["id"]


def list_existing_source_ids(
    database_url: str,
    *,
    workspace_id: str,
    index_kind: str,
) -> set[str]:
    """Return the set of ``source_id`` values already indexed for a
    given workspace and kind. Used by the backfill task to skip
    rows we already embedded.
    """
    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_id
                FROM retrieval_embeddings
                WHERE workspace_id = %s::uuid AND index_kind = %s
                """,
                (workspace_id, index_kind),
            )
            return {r["source_id"] for r in cur.fetchall()}


def count_by_kind(
    database_url: str,
    *,
    workspace_id: str,
) -> dict[str, int]:
    """Return ``{index_kind: count}`` for the workspace, used by the
    eval UI to show backfill state at a glance."""
    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT index_kind, COUNT(*) AS c
                FROM retrieval_embeddings
                WHERE workspace_id = %s::uuid
                GROUP BY index_kind
                """,
                (workspace_id,),
            )
            return {r["index_kind"]: int(r["c"]) for r in cur.fetchall()}


def search_by_kind(
    database_url: str,
    *,
    workspace_id: str,
    index_kind: str,
    query_embedding: list[float],
    top_k: int = 30,
    document_id: str | None = None,
    agent_id: str | None = None,
) -> list[dict[str, Any]]:
    """Cosine-similarity ANN search against rows of a given
    ``index_kind``. The Naive-RAG path always passes
    ``index_kind = 'raw_chunk'`` and never sees anything else.

    Returns hit rows ordered ascending by cosine distance (i.e. most
    similar first), each with the persisted columns plus a ``score``
    field equal to ``1 - distance`` so callers can treat it as a
    normalized similarity in ``[-1, 1]``.
    """
    if index_kind not in VALID_INDEX_KINDS:
        raise ValueError(f"unknown index_kind: {index_kind!r}")
    if not query_embedding:
        return []

    extra_filter = ""
    extra_params: list[Any] = []
    if document_id:
        extra_filter = " AND document_id = %s::uuid"
        extra_params.append(document_id)
    if agent_id:
        extra_filter += " AND agent_id = %s::uuid"
        extra_params.append(agent_id)

    # Positional ``%s`` placeholders in order: SELECT score expression,
    # WHERE workspace_id, WHERE index_kind, optional document filter,
    # ORDER BY embedding distance, LIMIT.
    params: list[Any] = [
        query_embedding,
        workspace_id,
        index_kind,
        *extra_params,
        query_embedding,
        int(top_k),
    ]

    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    id::text AS id,
                    workspace_id::text AS workspace_id,
                    index_kind,
                    source_kind,
                    source_id,
                    document_id::text AS document_id,
                    agent_id::text AS agent_id,
                    page_start,
                    page_end,
                    chunk_sequence,
                    text,
                    attributes,
                    1.0 - (embedding <=> %s::vector) AS score
                FROM retrieval_embeddings
                WHERE workspace_id = %s::uuid
                  AND index_kind = %s
                  {extra_filter}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "workspace_id": r["workspace_id"],
                "index_kind": r["index_kind"],
                "source_kind": r["source_kind"],
                "source_id": r["source_id"],
                "document_id": r["document_id"],
                "agent_id": r["agent_id"],
                "page_start": r["page_start"],
                "page_end": r["page_end"],
                "chunk_sequence": r["chunk_sequence"],
                "text": r["text"],
                "attributes": dict(r["attributes"] or {}),
                "score": float(r["score"]) if r["score"] is not None else 0.0,
            }
        )
    return out


def delete_for_document(
    database_url: str,
    *,
    workspace_id: str,
    document_id: str,
    index_kind: str | None = None,
) -> int:
    """Delete all embeddings tied to a given document (optionally
    restricted by ``index_kind``). Called by the document-delete
    cascade so a deleted PDF can't poison subsequent eval runs.
    """
    sql = (
        "DELETE FROM retrieval_embeddings "
        "WHERE workspace_id = %s::uuid AND document_id = %s::uuid"
    )
    params: list[Any] = [workspace_id, document_id]
    if index_kind is not None:
        sql += " AND index_kind = %s"
        params.append(index_kind)
    with _connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            count = cur.rowcount or 0
            conn.commit()
    return int(count)
