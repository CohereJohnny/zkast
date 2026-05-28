"""Durable token / usage accounting for dashboard rollups."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

VALID_SOURCES = frozenset({"chat", "ingestion", "wiki", "dream", "eval", "retrieval", "other"})


def insert_usage_event(
    database_url: str,
    *,
    workspace_id: str,
    usage_source: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    agent_id: str | None = None,
    north_conversation_id: str | None = None,
    document_id: str | None = None,
    job_id: str | None = None,
    ingestion_run_id: str | None = None,
    stage: str | None = None,
    model: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if usage_source not in VALID_SOURCES:
        usage_source = "other"
    tin = max(0, int(tokens_in))
    tout = max(0, int(tokens_out))
    if tin == 0 and tout == 0:
        return
    eid = str(uuid4())
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO usage_events (
              id, workspace_id, agent_id, north_conversation_id, document_id,
              job_id, ingestion_run_id, usage_source, stage, model,
              tokens_in, tokens_out, metadata
            )
            VALUES (
              %s::uuid, %s::uuid, %s::uuid, %s, %s::uuid,
              %s, %s::uuid, %s, %s, %s,
              %s, %s, %s::jsonb
            )
            """,
            (
                eid,
                workspace_id,
                agent_id,
                north_conversation_id,
                document_id,
                job_id,
                ingestion_run_id,
                usage_source,
                stage,
                model,
                tin,
                tout,
                Json(metadata or {}),
            ),
        )
        conn.commit()


def record_ingestion_tokens(
    database_url: str,
    *,
    workspace_id: str,
    tokens: int,
    stage: str,
    agent_id: str | None = None,
    document_id: str | None = None,
    job_id: str | None = None,
    ingestion_run_id: str | None = None,
    model: str | None = None,
) -> None:
    """Persist ingestion-stage token deltas (previously Redis-only metrics)."""
    insert_usage_event(
        database_url,
        workspace_id=workspace_id,
        usage_source="ingestion",
        tokens_out=max(0, int(tokens)),
        agent_id=agent_id,
        document_id=document_id,
        job_id=job_id,
        ingestion_run_id=ingestion_run_id,
        stage=stage,
        model=model,
        metadata={"metric": "tokens_consumed"},
    )


def usage_totals_by_source(
    database_url: str, *, workspace_id: str, agent_id: str | None = None
) -> dict[str, dict[str, int]]:
    sql = """
        SELECT usage_source,
               COALESCE(SUM(tokens_in), 0)::bigint AS tokens_in,
               COALESCE(SUM(tokens_out), 0)::bigint AS tokens_out,
               COUNT(*)::int AS event_count
        FROM usage_events
        WHERE workspace_id = %s::uuid
    """
    params: list[Any] = [workspace_id]
    if agent_id:
        sql += " AND agent_id = %s::uuid"
        params.append(agent_id)
    sql += " GROUP BY usage_source ORDER BY usage_source"
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(sql, params).fetchall()
    out: dict[str, dict[str, int]] = {}
    for row in rows:
        src = str(row["usage_source"])
        out[src] = {
            "tokens_in": int(row["tokens_in"]),
            "tokens_out": int(row["tokens_out"]),
            "event_count": int(row["event_count"]),
        }
    return out


def usage_totals_workspace(database_url: str, *, workspace_id: str) -> dict[str, int]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT
              COALESCE(SUM(tokens_in), 0)::bigint AS tokens_in,
              COALESCE(SUM(tokens_out), 0)::bigint AS tokens_out,
              COUNT(*)::int AS event_count
            FROM usage_events
            WHERE workspace_id = %s::uuid
            """,
            (workspace_id,),
        ).fetchone()
    if not row:
        return {"tokens_in": 0, "tokens_out": 0, "event_count": 0}
    return {
        "tokens_in": int(row["tokens_in"]),
        "tokens_out": int(row["tokens_out"]),
        "event_count": int(row["event_count"]),
    }
