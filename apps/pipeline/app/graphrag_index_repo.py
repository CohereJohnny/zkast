"""Postgres repo for graphrag_indexes (MS GraphRAG artifact registry)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row)
    for key in ("id", "workspace_id", "agent_id", "configuration_id"):
        if r.get(key) is not None:
            r[key] = str(r[key])
    for ts in ("started_at", "ended_at", "created_at", "updated_at"):
        v = r.get(ts)
        if v is not None and hasattr(v, "isoformat"):
            r[ts] = v.isoformat()
    if r.get("stats") is not None and not isinstance(r["stats"], dict):
        r["stats"] = dict(r["stats"])
    return r


def insert_graphrag_index(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str | None,
    configuration_id: str | None,
    provider: str,
    embedding_dim: int,
    ontology_name: str | None,
    ontology_version: str | None,
    job_id: str | None = None,
) -> dict[str, Any]:
    gid = str(uuid4())
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            INSERT INTO graphrag_indexes (
              id, workspace_id, agent_id, configuration_id, status, provider,
              embedding_dim, ontology_name, ontology_version, job_id
            )
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, 'pending', %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                gid,
                workspace_id,
                agent_id,
                configuration_id,
                provider,
                int(embedding_dim),
                ontology_name,
                ontology_version,
                job_id,
            ),
        ).fetchone()
        conn.commit()
        assert row
    return _serialize(dict(row))


def mark_running(database_url: str, *, index_id: str) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE graphrag_indexes SET status='running', started_at=now(), updated_at=now() "
            "WHERE id=%s::uuid",
            (index_id,),
        )
        conn.commit()


def mark_ready(
    database_url: str, *, index_id: str, artifact_uri: str, stats: dict[str, Any]
) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE graphrag_indexes SET status='ready', artifact_uri=%s, stats=%s::jsonb, "
            "ended_at=now(), updated_at=now() WHERE id=%s::uuid",
            (artifact_uri, Json(stats), index_id),
        )
        conn.commit()


def mark_failed(database_url: str, *, index_id: str, reason: str) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE graphrag_indexes SET status='failed', failure_reason=%s, ended_at=now(), "
            "updated_at=now() WHERE id=%s::uuid",
            (reason[:2000], index_id),
        )
        conn.commit()


def fetch_graphrag_index(database_url: str, *, index_id: str) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT * FROM graphrag_indexes WHERE id=%s::uuid LIMIT 1", (index_id,)
        ).fetchone()
    return _serialize(dict(row)) if row else None


def fetch_latest_index(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str | None,
    configuration_id: str | None = None,
) -> dict[str, Any] | None:
    clauses = ["workspace_id = %s::uuid"]
    args: list[Any] = [workspace_id]
    clauses.append("agent_id IS NOT DISTINCT FROM %s::uuid")
    args.append(agent_id)
    if configuration_id is not None:
        clauses.append("configuration_id = %s::uuid")
        args.append(configuration_id)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            f"SELECT * FROM graphrag_indexes WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC LIMIT 1",
            tuple(args),
        ).fetchone()
    return _serialize(dict(row)) if row else None


def list_graphrag_indexes(database_url: str, *, workspace_id: str) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            "SELECT * FROM graphrag_indexes WHERE workspace_id=%s::uuid "
            "ORDER BY created_at DESC LIMIT 200",
            (workspace_id,),
        ).fetchall()
    return [_serialize(dict(r)) for r in rows]
