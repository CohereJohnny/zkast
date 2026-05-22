"""Relationship rows + Graphiti edge mapping (sync psycopg)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row


def insert_relationship_from_graphiti(
    database_url: str,
    *,
    workspace_id: str,
    graphiti_edge_uuid: str,
    source_entity_id: str,
    target_entity_id: str,
    rel_type: str,
    fact: str,
    confidence: float,
    valid_from: datetime | None,
    valid_to: datetime | None,
    episode_id: str | None,
    note_id: str | None,
    agent_id: str | None = None,
) -> str:
    fact = (fact or "")[:500]
    rel_type = (rel_type or "RELATED_TO")[:120]

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        hit = conn.execute(
            "SELECT relationship_id::text FROM graphiti_edge_map WHERE graphiti_uuid = %s",
            (graphiti_edge_uuid,),
        ).fetchone()
        if hit:
            rid = hit["relationship_id"]
            _prov(conn, rid, episode_id, note_id)
            conn.commit()
            return rid

        rid = str(uuid4())
        conn.execute(
            """
            INSERT INTO relationships (
              id, workspace_id, agent_id, source_entity_id, target_entity_id,
              type, fact, valid_from, valid_to, confidence, origin, is_user_edited
            )
            VALUES (
              %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid,
              %s, %s, %s, %s, %s, 'generated', false
            )
            """,
            (
                rid,
                workspace_id,
                agent_id,
                source_entity_id,
                target_entity_id,
                rel_type,
                fact,
                valid_from,
                valid_to,
                float(confidence),
            ),
        )
        conn.execute(
            """
            INSERT INTO graphiti_edge_map (graphiti_uuid, relationship_id, workspace_id, agent_id)
            VALUES (%s, %s::uuid, %s::uuid, %s::uuid)
            """,
            (graphiti_edge_uuid, rid, workspace_id, agent_id),
        )
        _prov(conn, rid, episode_id, note_id)
        conn.commit()
    return rid


def _prov(conn: psycopg.Connection, relationship_id: str, episode_id: str | None, note_id: str | None) -> None:
    if episode_id:
        conn.execute(
            """
            INSERT INTO relationship_episodes (relationship_id, episode_id)
            VALUES (%s::uuid, %s::uuid)
            ON CONFLICT (relationship_id, episode_id) DO NOTHING
            """,
            (relationship_id, episode_id),
        )
    if note_id:
        conn.execute(
            """
            INSERT INTO relationship_notes (relationship_id, note_id)
            VALUES (%s::uuid, %s::uuid)
            ON CONFLICT (relationship_id, note_id) DO NOTHING
            """,
            (relationship_id, note_id),
        )
