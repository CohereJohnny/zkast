"""Persistence for merge_audit_log — backs the 'Full undo' unmerge flow.

Each merge call (entity or note) captures enough state to restore the
deleted victim row and its provenance. ``undone_at`` flips when unmerge
runs so we don't try to undo twice.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def insert_merge_audit(
    conn: psycopg.Connection,
    *,
    workspace_id: str,
    kind: str,  # 'entity' | 'note'
    survivor_id: str,
    victim_id: str,
    victim_payload: dict[str, Any],
    survivor_before: dict[str, Any],
    victim_provenance: dict[str, Any],
    incident_relationships: list[dict[str, Any]] | None = None,
) -> str:
    if kind not in ("entity", "note"):
        raise ValueError("kind must be 'entity' or 'note'")
    audit_id = str(uuid4())
    conn.execute(
        """
        INSERT INTO merge_audit_log
          (id, workspace_id, kind, survivor_id, victim_id,
           victim_payload, survivor_before, victim_provenance,
           incident_relationships)
        VALUES (%s::uuid, %s::uuid, %s, %s::uuid, %s::uuid,
                %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
        """,
        (
            audit_id,
            workspace_id,
            kind,
            survivor_id,
            victim_id,
            Json(victim_payload),
            Json(survivor_before),
            Json(victim_provenance),
            Json(incident_relationships) if incident_relationships is not None else None,
        ),
    )
    return audit_id


def fetch_latest_audit(
    database_url: str,
    *,
    workspace_id: str,
    kind: str,
    survivor_id: str,
) -> dict[str, Any] | None:
    """Return the most recent un-undone audit row for ``(kind, survivor_id)``."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT * FROM merge_audit_log
            WHERE workspace_id = %s::uuid
              AND kind = %s
              AND survivor_id = %s::uuid
              AND undone_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (workspace_id, kind, survivor_id),
        ).fetchone()
        return dict(row) if row else None


def mark_audit_undone(conn: psycopg.Connection, *, audit_id: str) -> None:
    conn.execute(
        "UPDATE merge_audit_log SET undone_at = now() WHERE id = %s::uuid",
        (audit_id,),
    )
