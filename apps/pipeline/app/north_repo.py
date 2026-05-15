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
        r = dict(row)
        _uuid(r, "id")
        _uuid(r, "workspace_id")
        return r


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
        r = dict(row)
        _uuid(r, "id")
        _uuid(r, "workspace_id")
        out.append(r)
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
    r = dict(row)
    _uuid(r, "id")
    _uuid(r, "workspace_id")
    return r


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
    agent_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT north_conversation_id, payload, fetched_at
            FROM north_conversation_cache
            WHERE agent_id = %s::uuid
            ORDER BY fetched_at DESC
            LIMIT %s
            """,
            (agent_id, limit),
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
