"""Entity rows + Graphiti UUID mapping (sync psycopg)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def entity_type_from_labels(labels: list[str] | None) -> str:
    if not labels:
        return "Concept"
    for lab in labels:
        if lab and lab != "Entity":
            return lab[:120]
    return "Concept"


def fetch_entity_id_for_graphiti_uuid(database_url: str, graphiti_uuid: str) -> str | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT entity_id::text FROM graphiti_entity_map WHERE graphiti_uuid = %s",
            (graphiti_uuid,),
        ).fetchone()
        return str(row["entity_id"]) if row else None


def upsert_entity_from_graphiti(
    database_url: str,
    *,
    workspace_id: str,
    graphiti_uuid: str,
    name: str,
    labels: list[str],
    summary: str,
    attributes: dict[str, Any],
    episode_id: str | None,
    note_id: str | None,
) -> str:
    """Returns zkast entity UUID string."""
    etype = entity_type_from_labels(labels)
    canonical = (name or "").strip()[:500] or "Unknown"
    summary = (summary or "")[:2000]

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        existing_map = conn.execute(
            "SELECT entity_id::text FROM graphiti_entity_map WHERE graphiti_uuid = %s",
            (graphiti_uuid,),
        ).fetchone()
        if existing_map:
            eid = existing_map["entity_id"]
            conn.execute(
                """
                UPDATE entities SET summary = COALESCE(NULLIF(summary,''), %s),
                  updated_at = now()
                WHERE id = %s::uuid
                """,
                (summary, eid),
            )
            _add_provenance(conn, entity_id=eid, episode_id=episode_id, note_id=note_id)
            conn.commit()
            return eid

        row = conn.execute(
            """
            SELECT id FROM entities
            WHERE workspace_id = %s::uuid AND type = %s AND lower(canonical_name) = lower(%s)
            LIMIT 1
            """,
            (workspace_id, etype, canonical),
        ).fetchone()
        if row:
            eid = str(row["id"])
            conn.execute(
                """
                INSERT INTO graphiti_entity_map (graphiti_uuid, entity_id, workspace_id)
                VALUES (%s, %s::uuid, %s::uuid)
                ON CONFLICT (graphiti_uuid) DO NOTHING
                """,
                (graphiti_uuid, eid, workspace_id),
            )
            conn.execute(
                """
                UPDATE entities SET summary = CASE WHEN length(summary) < length(%s) THEN %s ELSE summary END,
                  updated_at = now()
                WHERE id = %s::uuid
                """,
                (summary, summary, eid),
            )
            _add_provenance(conn, entity_id=eid, episode_id=episode_id, note_id=note_id)
            conn.commit()
            return eid

        eid = str(uuid4())
        conn.execute(
            """
            INSERT INTO entities (
              id, workspace_id, type, canonical_name, aliases, summary, properties, is_user_edited
            )
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, false)
            """,
            (
                eid,
                workspace_id,
                etype,
                canonical,
                [],
                summary,
                Json(attributes or {}),
            ),
        )
        conn.execute(
            """
            INSERT INTO graphiti_entity_map (graphiti_uuid, entity_id, workspace_id)
            VALUES (%s, %s::uuid, %s::uuid)
            """,
            (graphiti_uuid, eid, workspace_id),
        )
        _add_provenance(conn, entity_id=eid, episode_id=episode_id, note_id=note_id)
        conn.commit()
    return eid


def _add_provenance(
    conn: psycopg.Connection,
    *,
    entity_id: str,
    episode_id: str | None,
    note_id: str | None,
) -> None:
    if episode_id:
        conn.execute(
            """
            INSERT INTO entity_episodes (entity_id, episode_id)
            VALUES (%s::uuid, %s::uuid)
            ON CONFLICT (entity_id, episode_id) DO NOTHING
            """,
            (entity_id, episode_id),
        )
    if note_id:
        conn.execute(
            """
            INSERT INTO entity_notes (entity_id, note_id)
            VALUES (%s::uuid, %s::uuid)
            ON CONFLICT (entity_id, note_id) DO NOTHING
            """,
            (entity_id, note_id),
        )


def resolve_entity_id_for_graphiti(database_url: str, graphiti_uuid: str) -> str | None:
    return fetch_entity_id_for_graphiti_uuid(database_url, graphiti_uuid)
