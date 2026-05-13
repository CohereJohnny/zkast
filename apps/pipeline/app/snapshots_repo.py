"""Immutable graph snapshots (freeze working entities, relationships, notes)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Json


class SnapshotError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def _entity_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "type": row["type"],
        "canonical_name": row["canonical_name"],
        "aliases": list(row.get("aliases") or []),
        "summary": row.get("summary") or "",
        "properties": row.get("properties") or {},
        "origin": "generated" if not row.get("is_user_edited") else "manual",
        "is_user_edited": bool(row.get("is_user_edited")),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _relationship_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "source_entity_id": str(row["source_entity_id"]),
        "target_entity_id": str(row["target_entity_id"]),
        "type": row["type"],
        "fact": row.get("fact") or "",
        "valid_from": _iso(row.get("valid_from")),
        "valid_to": _iso(row.get("valid_to")),
        "confidence": float(row["confidence"]) if row.get("confidence") is not None else 1.0,
        "origin": row.get("origin") or "generated",
        "is_user_edited": bool(row.get("is_user_edited")),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _note_payload(row: dict[str, Any], episode_ids: list[str]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "body": row.get("body") or "",
        "tags": list(row.get("tags") or []),
        "origin": row.get("origin") or "generated",
        "is_user_edited": bool(row.get("is_user_edited")),
        "source_episode_ids": episode_ids,
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _serialize_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if out.get("id") is not None:
        out["id"] = str(out["id"])
    if out.get("workspace_id") is not None:
        out["workspace_id"] = str(out["workspace_id"])
    if out.get("created_by_user_id") is not None:
        out["created_by_user_id"] = str(out["created_by_user_id"])
    ca = out.get("created_at")
    if isinstance(ca, datetime):
        out["created_at"] = ca.isoformat()
    return out


def create_snapshot(
    database_url: str,
    *,
    workspace_id: str,
    name: str,
    description: str | None,
    created_by_user_id: str | None,
) -> dict[str, Any]:
    name = name.strip()
    if not name or len(name) > 120:
        raise SnapshotError("validation_failed", "name must be 1–120 characters")
    if description is not None and len(description) > 1000:
        raise SnapshotError("validation_failed", "description too long")

    snap_id = str(uuid4())
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            n_ent = conn.execute(
                "SELECT count(*)::int AS c FROM entities WHERE workspace_id = %s::uuid",
                (workspace_id,),
            ).fetchone()
            if not n_ent or int(n_ent["c"]) == 0:
                raise SnapshotError("business_rule_violation", "Cannot snapshot an empty graph")

            ent_rows = conn.execute(
                "SELECT * FROM entities WHERE workspace_id = %s::uuid",
                (workspace_id,),
            ).fetchall()
            rel_rows = conn.execute(
                "SELECT * FROM relationships WHERE workspace_id = %s::uuid",
                (workspace_id,),
            ).fetchall()
            note_rows = conn.execute(
                "SELECT * FROM atomic_notes WHERE workspace_id = %s::uuid",
                (workspace_id,),
            ).fetchall()

            stats = {
                "entity_count": len(ent_rows),
                "relationship_count": len(rel_rows),
                "note_count": len(note_rows),
            }

            try:
                conn.execute(
                    """
                    INSERT INTO graph_snapshots (
                      id, workspace_id, name, description, created_by_user_id, stats
                    )
                    VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        snap_id,
                        workspace_id,
                        name,
                        description,
                        created_by_user_id,
                        Json(stats),
                    ),
                )
            except UniqueViolation as e:
                raise SnapshotError("conflict", "Snapshot name already used in this workspace") from e

            for er in ent_rows:
                d = dict(er)
                conn.execute(
                    """
                    INSERT INTO snapshot_entities (snapshot_id, source_entity_id, payload)
                    VALUES (%s::uuid, %s::uuid, %s::jsonb)
                    """,
                    (snap_id, str(d["id"]), Json(_entity_payload(d))),
                )

            for rr in rel_rows:
                d = dict(rr)
                conn.execute(
                    """
                    INSERT INTO snapshot_relationships (snapshot_id, source_relationship_id, payload)
                    VALUES (%s::uuid, %s::uuid, %s::jsonb)
                    """,
                    (snap_id, str(d["id"]), Json(_relationship_payload(d))),
                )

            for nr in note_rows:
                d = dict(nr)
                eps = conn.execute(
                    "SELECT episode_id::text FROM note_episodes WHERE note_id = %s::uuid",
                    (d["id"],),
                ).fetchall()
                ep_ids = [str(r["episode_id"]) for r in eps]
                conn.execute(
                    """
                    INSERT INTO snapshot_notes (snapshot_id, source_note_id, payload)
                    VALUES (%s::uuid, %s::uuid, %s::jsonb)
                    """,
                    (snap_id, str(d["id"]), Json(_note_payload(d, ep_ids))),
                )

    return fetch_snapshot(database_url, workspace_id=workspace_id, snapshot_id=snap_id) or {}


def list_snapshots(
    database_url: str,
    *,
    workspace_id: str,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        total = conn.execute(
            "SELECT count(*)::int AS c FROM graph_snapshots WHERE workspace_id = %s::uuid",
            (workspace_id,),
        ).fetchone()
        t = int(total["c"]) if total else 0
        rows = conn.execute(
            """
            SELECT * FROM graph_snapshots
            WHERE workspace_id = %s::uuid
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (workspace_id, limit, offset),
        ).fetchall()
        return [_serialize_snapshot(dict(r)) for r in rows], t


def fetch_snapshot(
    database_url: str, *, workspace_id: str, snapshot_id: str
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT * FROM graph_snapshots
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            (snapshot_id, workspace_id),
        ).fetchone()
        return _serialize_snapshot(dict(row)) if row else None


def delete_snapshot(database_url: str, *, workspace_id: str, snapshot_id: str) -> bool:
    with psycopg.connect(database_url) as conn:
        cur = conn.execute(
            "DELETE FROM graph_snapshots WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (snapshot_id, workspace_id),
        )
        conn.commit()
        return cur.rowcount > 0


def upsert_snapshot_review(
    database_url: str,
    *,
    snapshot_id: str,
    decision: str,
    notes: str | None,
    reviewed_by_user_id: str | None,
) -> dict[str, Any]:
    """Record (or update) a review decision for a snapshot.

    Single-row-per-snapshot semantics: re-submitting overwrites. ``decision``
    must be ``approved`` or ``rejected`` (CHECK constraint in migration 0007).
    """
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be 'approved' or 'rejected'")
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            INSERT INTO snapshot_reviews
              (snapshot_id, decision, notes, reviewed_by_user_id)
            VALUES (%s::uuid, %s, %s, %s::uuid)
            ON CONFLICT (snapshot_id) DO UPDATE
              SET decision = EXCLUDED.decision,
                  notes = EXCLUDED.notes,
                  reviewed_by_user_id = EXCLUDED.reviewed_by_user_id,
                  reviewed_at = now()
            RETURNING snapshot_id::text AS snapshot_id, decision, notes,
                      reviewed_by_user_id::text AS reviewed_by_user_id,
                      reviewed_at
            """,
            (snapshot_id, decision, notes, reviewed_by_user_id),
        ).fetchone()
        conn.commit()
        if not row:
            raise RuntimeError("snapshot_reviews upsert returned no row")
        out = dict(row)
        if isinstance(out.get("reviewed_at"), datetime):
            out["reviewed_at"] = out["reviewed_at"].isoformat()
        return out


def fetch_snapshot_review(
    database_url: str, *, snapshot_id: str
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT snapshot_id::text AS snapshot_id, decision, notes,
                   reviewed_by_user_id::text AS reviewed_by_user_id,
                   reviewed_at
            FROM snapshot_reviews
            WHERE snapshot_id = %s::uuid
            """,
            (snapshot_id,),
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        if isinstance(out.get("reviewed_at"), datetime):
            out["reviewed_at"] = out["reviewed_at"].isoformat()
        return out
