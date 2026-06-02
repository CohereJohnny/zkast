"""Persistence for North agents, conversation cache, and dream jobs."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def _uuid(row: dict[str, Any], key: str) -> None:
    if row.get(key) is not None:
        row[key] = str(row[key])


def _serialize_north_agent_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a copy safe for ``JSONResponse`` (datetimes are not JSON-serializable by default)."""
    r = dict(row)
    _uuid(r, "id")
    _uuid(r, "workspace_id")
    for ts in ("created_at", "updated_at"):
        v = r.get(ts)
        if v is not None and hasattr(v, "isoformat"):
            r[ts] = v.isoformat()
    return r
def upsert_north_agent(
    database_url: str,
    *,
    workspace_id: str,
    external_agent_id: str,
    display_name: str,
    provider: str = "north",
    import_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    aid = str(uuid4())
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            INSERT INTO north_agents (
              id, workspace_id, external_agent_id, provider, display_name, import_settings
            )
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s::jsonb)
            ON CONFLICT (workspace_id, provider, external_agent_id)
            DO UPDATE SET
              display_name = EXCLUDED.display_name,
              import_settings = EXCLUDED.import_settings,
              updated_at = now()
            RETURNING *
            """,
            (
                aid,
                workspace_id,
                external_agent_id,
                provider,
                display_name[:500],
                Json(import_settings or {}),
            ),
        ).fetchone()
        conn.commit()
        assert row
        return _serialize_north_agent_row(dict(row))


def list_north_agents(database_url: str, *, workspace_id: str) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT * FROM north_agents
            WHERE workspace_id = %s::uuid
            ORDER BY display_name ASC, created_at ASC
            """,
            (workspace_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(_serialize_north_agent_row(dict(row)))
    return out


def fetch_north_agent(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT * FROM north_agents
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            LIMIT 1
            """,
            (agent_id, workspace_id),
        ).fetchone()
    if not row:
        return None
    return _serialize_north_agent_row(dict(row))


def fetch_agent_stats(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str,
) -> dict[str, Any]:
    """Counts for agent detail UI (documents, notes, embeddings)."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        doc_row = conn.execute(
            """
            SELECT count(*)::int AS c
            FROM documents
            WHERE workspace_id = %s::uuid
              AND agent_id = %s::uuid
              AND source_kind IN ('north_conversation', 'slack_conversation')
            """,
            (workspace_id, agent_id),
        ).fetchone()
        note_row = conn.execute(
            """
            SELECT count(*)::int AS c
            FROM atomic_notes
            WHERE workspace_id = %s::uuid AND agent_id = %s::uuid
            """,
            (workspace_id, agent_id),
        ).fetchone()
        cache_row = conn.execute(
            """
            SELECT count(*)::int AS c
            FROM north_conversation_cache
            WHERE workspace_id = %s::uuid AND agent_id = %s::uuid
            """,
            (workspace_id, agent_id),
        ).fetchone()
        amem_row = conn.execute(
            """
            SELECT count(*)::int AS c
            FROM retrieval_embeddings re
            WHERE re.workspace_id = %s::uuid
              AND re.agent_id = %s::uuid
              AND re.index_kind = 'note_amem'
              AND re.source_kind = 'atomic_note'
              AND EXISTS (
                SELECT 1 FROM atomic_notes n
                WHERE n.workspace_id = re.workspace_id
                  AND n.id::text = re.source_id
                  AND n.agent_id = re.agent_id
              )
            """,
            (workspace_id, agent_id),
        ).fetchone()
        orphan_row = conn.execute(
            """
            SELECT count(*)::int AS c
            FROM retrieval_embeddings re
            WHERE re.workspace_id = %s::uuid
              AND re.agent_id = %s::uuid
              AND re.index_kind = 'note_amem'
              AND re.source_kind = 'atomic_note'
              AND NOT EXISTS (
                SELECT 1 FROM atomic_notes n
                WHERE n.workspace_id = re.workspace_id
                  AND n.id::text = re.source_id
              )
            """,
            (workspace_id, agent_id),
        ).fetchone()
    return {
        "imported_documents": int(doc_row["c"]) if doc_row else 0,
        "derived_notes": int(note_row["c"]) if note_row else 0,
        "cached_conversations": int(cache_row["c"]) if cache_row else 0,
        "note_amem_embeddings": int(amem_row["c"]) if amem_row else 0,
        "note_amem_orphaned": int(orphan_row["c"]) if orphan_row else 0,
    }


def fetch_conversation_memory_stats_by_agent(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str,
) -> dict[str, dict[str, Any]]:
    """Per north_conversation_id memory counts (latest import document)."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            WITH latest_docs AS (
              SELECT DISTINCT ON (d.north_conversation_id)
                d.north_conversation_id,
                d.id AS document_id,
                d.status AS document_status,
                d.north_metadata
              FROM documents d
              WHERE d.workspace_id = %s::uuid
                AND d.agent_id = %s::uuid
                AND d.source_kind = 'north_conversation'
                AND d.north_conversation_id IS NOT NULL
              ORDER BY d.north_conversation_id, d.created_at DESC
            ),
            note_agg AS (
              SELECT ld.north_conversation_id, count(DISTINCT n.id)::int AS note_count
              FROM latest_docs ld
              LEFT JOIN episodes e ON e.document_id = ld.document_id
              LEFT JOIN note_episodes ne ON ne.episode_id = e.id
              LEFT JOIN atomic_notes n ON n.id = ne.note_id
              GROUP BY ld.north_conversation_id
            ),
            amem_agg AS (
              SELECT ld.north_conversation_id, count(DISTINCT re.id)::int AS amem_count
              FROM latest_docs ld
              LEFT JOIN episodes e ON e.document_id = ld.document_id
              LEFT JOIN note_episodes ne ON ne.episode_id = e.id
              LEFT JOIN atomic_notes n ON n.id = ne.note_id
              LEFT JOIN retrieval_embeddings re
                ON re.workspace_id = %s::uuid
               AND re.index_kind = 'note_amem'
               AND re.source_kind = 'atomic_note'
               AND n.id IS NOT NULL
               AND re.source_id = n.id::text
              GROUP BY ld.north_conversation_id
            )
            SELECT
              ld.north_conversation_id,
              ld.document_id::text AS document_id,
              ld.document_status,
              ld.north_metadata,
              coalesce(n.note_count, 0) AS note_count,
              coalesce(a.amem_count, 0) AS amem_count
            FROM latest_docs ld
            LEFT JOIN note_agg n ON n.north_conversation_id = ld.north_conversation_id
            LEFT JOIN amem_agg a ON a.north_conversation_id = ld.north_conversation_id
            """,
            (workspace_id, agent_id, workspace_id),
        ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        cid = str(row.get("north_conversation_id") or "").strip()
        if not cid:
            continue
        meta = row.get("north_metadata")
        ingest_hash: str | None = None
        if isinstance(meta, dict):
            raw = meta.get("ingest_content_hash")
            ingest_hash = str(raw) if raw else None
        out[cid] = {
            "document_id": str(row.get("document_id") or ""),
            "document_status": str(row.get("document_status") or ""),
            "notes": int(row.get("note_count") or 0),
            "amem_embeddings": int(row.get("amem_count") or 0),
            "ingest_digest": ingest_hash[:12] if ingest_hash else None,
        }
    return out


def update_agent_sync_cursor(
    database_url: str,
    *,
    agent_id: str,
    cursor: str | None,
) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            UPDATE north_agents
            SET sync_cursor = %s, updated_at = now()
            WHERE id = %s::uuid
            """,
            (cursor, agent_id),
        )
        conn.commit()


def upsert_conversation_cache(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str,
    north_conversation_id: str,
    payload: dict[str, Any],
) -> None:
    cid = str(uuid4())
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO north_conversation_cache (
              id, workspace_id, agent_id, north_conversation_id, payload, fetched_at
            )
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, now())
            ON CONFLICT (agent_id, north_conversation_id)
            DO UPDATE SET
              payload = EXCLUDED.payload,
              fetched_at = now()
            """,
            (cid, workspace_id, agent_id, north_conversation_id, Json(payload)),
        )
        conn.commit()


def list_conversation_cache(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT ncc.north_conversation_id, ncc.payload, ncc.fetched_at
            FROM north_conversation_cache ncc
            INNER JOIN north_agents na ON na.id = ncc.agent_id
            WHERE na.workspace_id = %s::uuid AND ncc.agent_id = %s::uuid
            ORDER BY ncc.fetched_at DESC
            LIMIT %s
            """,
            (workspace_id, agent_id, limit),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "north_conversation_id": r["north_conversation_id"],
                "payload": dict(r["payload"]) if isinstance(r["payload"], dict) else r["payload"],
                "fetched_at": r["fetched_at"].isoformat() if r["fetched_at"] else None,
            },
        )
    return out


def fetch_conversation_cache(
    database_url: str,
    *,
    agent_id: str,
    north_conversation_id: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT payload FROM north_conversation_cache
            WHERE agent_id = %s::uuid AND north_conversation_id = %s
            LIMIT 1
            """,
            (agent_id, north_conversation_id),
        ).fetchone()
    if not row:
        return None
    return dict(row["payload"]) if isinstance(row["payload"], dict) else {"raw": row["payload"]}


def insert_dream_job(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str,
) -> str:
    job_id = str(uuid4())
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO dream_jobs (id, workspace_id, agent_id, status, stats)
            VALUES (%s::uuid, %s::uuid, %s::uuid, 'running', '{}'::jsonb)
            """,
            (job_id, workspace_id, agent_id),
        )
        conn.commit()
    return job_id


def finalize_dream_job(
    database_url: str,
    *,
    job_id: str,
    status: str,
    stats: dict[str, Any] | None = None,
    failure_reason: str | None = None,
) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            UPDATE dream_jobs
            SET status = %s,
                stats = COALESCE(%s::jsonb, stats),
                failure_reason = %s,
                ended_at = now()
            WHERE id = %s::uuid
            """,
            (status, Json(stats or {}), failure_reason, job_id),
        )
        conn.commit()


def insert_dream_mutation(
    database_url: str,
    *,
    dream_job_id: str,
    note_id: str,
    mutation_type: str,
    payload: dict[str, Any],
) -> None:
    mid = str(uuid4())
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO dream_job_mutations (id, dream_job_id, note_id, mutation_type, payload)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb)
            """,
            (mid, dream_job_id, note_id, mutation_type, Json(payload)),
        )
        conn.commit()


def _serialize_dream_job_row(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row)
    for key in ("id", "workspace_id", "agent_id"):
        if r.get(key) is not None:
            r[key] = str(r[key])
    for ts in ("started_at", "ended_at"):
        v = r.get(ts)
        if v is not None and hasattr(v, "isoformat"):
            r[ts] = v.isoformat()
    stats = r.get("stats")
    if stats is not None and not isinstance(stats, dict):
        r["stats"] = dict(stats)
    return r


def list_workspace_dream_jobs(
    database_url: str,
    *,
    workspace_id: str,
    limit: int = 30,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
              id, workspace_id, agent_id, status, stats, failure_reason,
              started_at, ended_at
            FROM dream_jobs
            WHERE workspace_id = %s::uuid
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (workspace_id, int(limit)),
        ).fetchall()
    return [_serialize_dream_job_row(dict(r)) for r in rows]


def list_dream_jobs(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
              id, workspace_id, agent_id, status, stats, failure_reason,
              started_at, ended_at
            FROM dream_jobs
            WHERE workspace_id = %s::uuid AND agent_id = %s::uuid
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (workspace_id, agent_id, int(limit)),
        ).fetchall()
    return [_serialize_dream_job_row(dict(r)) for r in rows]


def fetch_dream_job(
    database_url: str,
    *,
    workspace_id: str,
    job_id: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT
              id, workspace_id, agent_id, status, stats, failure_reason,
              started_at, ended_at
            FROM dream_jobs
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            LIMIT 1
            """,
            (job_id, workspace_id),
        ).fetchone()
    if not row:
        return None
    return _serialize_dream_job_row(dict(row))


def list_dream_job_mutations(
    database_url: str,
    *,
    dream_job_id: str,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
              id::text AS id,
              dream_job_id::text AS dream_job_id,
              note_id::text AS note_id,
              mutation_type,
              payload,
              created_at
            FROM dream_job_mutations
            WHERE dream_job_id = %s::uuid
            ORDER BY created_at ASC
            """,
            (dream_job_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        if item.get("created_at") and hasattr(item["created_at"], "isoformat"):
            item["created_at"] = item["created_at"].isoformat()
        if item.get("payload") is not None and not isinstance(item["payload"], dict):
            item["payload"] = dict(item["payload"])
        out.append(item)
    return out
