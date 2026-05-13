"""Durable per-ingestion-run log storage.

Backs the streaming console drawer (live tail) and the Diagnostics page
(historical lookup). Writes are best-effort: failures here never propagate
to the worker.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def insert_log_row(
    database_url: str,
    *,
    ingestion_run_id: str,
    level: str,
    stage: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Append one row to ``ingestion_run_logs``.

    ``level`` must be one of ``info`` / ``warning`` / ``error`` (DB
    check-constraint). The caller is responsible for trimming ``message`` to
    something reasonable; we don't truncate here.
    """
    if level not in ("info", "warning", "error"):
        level = "info"
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO ingestion_run_logs (id, ingestion_run_id, level, stage, message, data)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s::jsonb)
            """,
            (
                str(uuid4()),
                ingestion_run_id,
                level,
                stage,
                message,
                Json(data) if data is not None else None,
            ),
        )
        conn.commit()


def list_logs_for_run(
    database_url: str,
    *,
    ingestion_run_id: str,
    limit: int = 500,
    after_ts: datetime | None = None,
    level: str | None = None,
) -> list[dict[str, Any]]:
    """Return rows newest-first for a single ingestion run."""
    clauses = ["ingestion_run_id = %s::uuid"]
    params: list[Any] = [ingestion_run_id]
    if after_ts is not None:
        clauses.append("ts > %s")
        params.append(after_ts)
    if level is not None:
        clauses.append("level = %s")
        params.append(level)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            f"""
            SELECT id::text, ts, level, stage, message, data
            FROM ingestion_run_logs
            WHERE {' AND '.join(clauses)}
            ORDER BY ts DESC
            LIMIT %s
            """,
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def list_logs_for_document(
    database_url: str,
    *,
    document_id: str,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return rows newest-first across all runs of a document."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
              l.id::text,
              l.ts,
              l.level,
              l.stage,
              l.message,
              l.data,
              l.ingestion_run_id::text AS ingestion_run_id
            FROM ingestion_run_logs l
            JOIN ingestion_runs ir ON ir.id = l.ingestion_run_id
            WHERE ir.document_id = %s::uuid
            ORDER BY l.ts DESC
            LIMIT %s
            """,
            (document_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def stage_latency_stats(
    database_url: str,
    *,
    workspace_id: str | None = None,
    window_hours: int = 24,
) -> list[dict[str, Any]]:
    """Rough P50 / P95 wall time per stage from `ingestion_runs.stats`.

    The pipeline already writes ``{stage: 'parsing_done', ...}`` into stats;
    we use the runs themselves (started_at..ended_at) bucketed by the
    document status they reached. Cheap aggregate for the Diagnostics page.
    """
    clauses = ["ir.ended_at IS NOT NULL", "ir.started_at >= now() - make_interval(hours => %s)"]
    params: list[Any] = [window_hours]
    if workspace_id is not None:
        clauses.append("d.workspace_id = %s::uuid")
        params.append(workspace_id)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            f"""
            SELECT
              ir.status AS status,
              percentile_cont(0.5)  WITHIN GROUP (
                ORDER BY EXTRACT(epoch FROM (ir.ended_at - ir.started_at))
              ) AS p50,
              percentile_cont(0.95) WITHIN GROUP (
                ORDER BY EXTRACT(epoch FROM (ir.ended_at - ir.started_at))
              ) AS p95,
              count(*) AS n
            FROM ingestion_runs ir
            JOIN documents d ON d.id = ir.document_id
            WHERE {' AND '.join(clauses)}
            GROUP BY ir.status
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]
