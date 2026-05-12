"""Document delete preview and exclusive-derivatives cascade (sync psycopg)."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row


def preview_document_delete(
    database_url: str,
    *,
    workspace_id: str,
    document_id: str,
) -> dict[str, Any]:
    """Return counts for modal (US-1.5 AC-1)."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        exclusive_notes = conn.execute(
            """
            SELECT n.id::text AS id
            FROM atomic_notes n
            WHERE n.workspace_id = %s::uuid
              AND EXISTS (
                SELECT 1 FROM note_episodes ne
                JOIN episodes e ON e.id = ne.episode_id
                WHERE ne.note_id = n.id AND e.document_id = %s::uuid
              )
              AND NOT EXISTS (
                SELECT 1 FROM note_episodes ne
                JOIN episodes e ON e.id = ne.episode_id
                WHERE ne.note_id = n.id AND e.document_id IS DISTINCT FROM %s::uuid
              )
            """,
            (workspace_id, document_id, document_id),
        ).fetchall()

        shared_notes = conn.execute(
            """
            SELECT n.id::text AS id
            FROM atomic_notes n
            WHERE n.workspace_id = %s::uuid
              AND EXISTS (
                SELECT 1 FROM note_episodes ne
                JOIN episodes e ON e.id = ne.episode_id
                WHERE ne.note_id = n.id AND e.document_id = %s::uuid
              )
              AND EXISTS (
                SELECT 1 FROM note_episodes ne
                JOIN episodes e ON e.id = ne.episode_id
                WHERE ne.note_id = n.id AND e.document_id <> %s::uuid
              )
            """,
            (workspace_id, document_id, document_id),
        ).fetchall()

        ep_sq = "SELECT id FROM episodes WHERE document_id = %s::uuid AND workspace_id = %s::uuid"

        entities_affected = conn.execute(
            f"""
            SELECT DISTINCT en.entity_id::text AS id
            FROM entity_episodes en
            WHERE en.episode_id IN ({ep_sq})
            """,
            (document_id, workspace_id),
        ).fetchall()

        rel_affected = conn.execute(
            f"""
            SELECT DISTINCT re.relationship_id::text AS id
            FROM relationship_episodes re
            WHERE re.episode_id IN ({ep_sq})
            """,
            (document_id, workspace_id),
        ).fetchall()

    return {
        "exclusive_note_ids": [r["id"] for r in exclusive_notes],
        "shared_note_ids": [r["id"] for r in shared_notes],
        "exclusive_note_count": len(exclusive_notes),
        "shared_note_count": len(shared_notes),
        "entity_touch_count": len(entities_affected),
        "relationship_touch_count": len(rel_affected),
    }


def execute_exclusive_derivatives_delete(
    database_url: str,
    *,
    workspace_id: str,
    document_id: str,
) -> dict[str, int]:
    """Delete notes exclusive to document; remove orphan entities/relationships."""
    preview = preview_document_delete(database_url, workspace_id=workspace_id, document_id=document_id)
    removed_notes = 0
    removed_entities = 0
    removed_relationships = 0

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        for nid in preview["exclusive_note_ids"]:
            cur = conn.execute(
                "DELETE FROM atomic_notes WHERE id = %s::uuid AND workspace_id = %s::uuid",
                (nid, workspace_id),
            )
            removed_notes += cur.rowcount

        orphan_entities = conn.execute(
            """
            SELECT e.id FROM entities e
            WHERE e.workspace_id = %s::uuid
              AND NOT EXISTS (SELECT 1 FROM entity_episodes ee WHERE ee.entity_id = e.id)
              AND NOT EXISTS (SELECT 1 FROM entity_notes en WHERE en.entity_id = e.id)
            """,
            (workspace_id,),
        ).fetchall()
        for row in orphan_entities:
            cur = conn.execute("DELETE FROM entities WHERE id = %s", (row["id"],))
            removed_entities += cur.rowcount

        orphan_rels = conn.execute(
            """
            SELECT r.id FROM relationships r
            WHERE r.workspace_id = %s::uuid
              AND NOT EXISTS (SELECT 1 FROM relationship_episodes re WHERE re.relationship_id = r.id)
              AND NOT EXISTS (SELECT 1 FROM relationship_notes rn WHERE rn.relationship_id = r.id)
            """,
            (workspace_id,),
        ).fetchall()
        for row in orphan_rels:
            cur = conn.execute("DELETE FROM relationships WHERE id = %s", (row["id"],))
            removed_relationships += cur.rowcount

        conn.commit()

    return {
        "removed_notes": removed_notes,
        "removed_entities": removed_entities,
        "removed_relationships": removed_relationships,
    }
