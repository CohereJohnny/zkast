"""Graph curation: entity merge/patch/delete, relationship CRUD."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from psycopg.types.json import Json


def _serialize_entity_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if out.get("id") is not None:
        out["id"] = str(out["id"])
    if out.get("workspace_id") is not None:
        out["workspace_id"] = str(out["workspace_id"])
    return out


def patch_entity(
    database_url: str,
    *,
    workspace_id: str,
    entity_id: str,
    canonical_name: str | None = None,
    type_: str | None = None,
    aliases: list[str] | None = None,
    summary: str | None = None,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    sets: list[str] = ["updated_at = now()", "is_user_edited = true"]
    params: list[Any] = []
    if canonical_name is not None:
        sets.append("canonical_name = %s")
        params.append(canonical_name.strip()[:500] or "Unknown")
    if type_ is not None:
        sets.append("type = %s")
        params.append(type_.strip()[:120] or "Concept")
    if aliases is not None:
        sets.append("aliases = %s")
        params.append(aliases)
    if summary is not None:
        sets.append("summary = %s")
        params.append(summary[:2000])
    if properties is not None:
        sets.append("properties = %s::jsonb")
        params.append(Json(properties))
    if len(sets) <= 2:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE id = %s::uuid AND workspace_id = %s::uuid",
                (entity_id, workspace_id),
            ).fetchone()
            return _serialize_entity_row(dict(row)) if row else None
    params.extend([entity_id, workspace_id])
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                f"""
                UPDATE entities SET {", ".join(sets)}
                WHERE id = %s::uuid AND workspace_id = %s::uuid
                RETURNING *
                """,
                params,
            ).fetchone()
            conn.commit()
            return _serialize_entity_row(dict(row)) if row else None
    except pg_errors.UniqueViolation:
        return None


def _dedupe_parallel_relationships(conn: psycopg.Connection, *, workspace_id: str) -> None:
    conn.execute(
        """
        DELETE FROM relationships a
        USING relationships b
        WHERE a.workspace_id = %s::uuid AND b.workspace_id = a.workspace_id
          AND a.source_entity_id = b.source_entity_id
          AND a.target_entity_id = b.target_entity_id
          AND a.type = b.type
          AND a.id > b.id
        """,
        (workspace_id,),
    )


def merge_entities(
    database_url: str,
    *,
    workspace_id: str,
    survivor_id: str,
    victim_id: str,
    field_selection: dict[str, str],
) -> dict[str, Any] | None:
    """field_selection keys: canonical_name, type, aliases, summary, properties — values survivor|other.

    Sprint 5b: writes a ``merge_audit_log`` row capturing the victim's full
    state + survivor's pre-merge state + victim provenance so ``unmerge_entity``
    can restore everything.
    """
    from app.merge_audit_repo import insert_merge_audit  # avoid circular import

    if survivor_id == victim_id:
        return None
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        a = conn.execute(
            "SELECT * FROM entities WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (survivor_id, workspace_id),
        ).fetchone()
        b = conn.execute(
            "SELECT * FROM entities WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (victim_id, workspace_id),
        ).fetchone()
        if not a or not b:
            return None
        da, db = dict(a), dict(b)

        # Snapshot enough state to unmerge cleanly. Capture provenance
        # junctions and the relationships about to be rewired.
        victim_episodes = [
            str(r["episode_id"])
            for r in conn.execute(
                "SELECT episode_id FROM entity_episodes WHERE entity_id = %s::uuid",
                (victim_id,),
            ).fetchall()
        ]
        victim_notes = [
            str(r["note_id"])
            for r in conn.execute(
                "SELECT note_id FROM entity_notes WHERE entity_id = %s::uuid",
                (victim_id,),
            ).fetchall()
        ]
        incident_rel_rows = conn.execute(
            """
            SELECT id::text AS id,
                   source_entity_id::text AS source_entity_id,
                   target_entity_id::text AS target_entity_id,
                   type, fact, valid_from, valid_to, origin, is_user_edited
            FROM relationships
            WHERE workspace_id = %s::uuid
              AND (source_entity_id = %s::uuid OR target_entity_id = %s::uuid)
            """,
            (workspace_id, victim_id, victim_id),
        ).fetchall()
        from datetime import datetime as _dt

        def _ser_rel(r: dict[str, Any]) -> dict[str, Any]:
            out = dict(r)
            for k in ("valid_from", "valid_to"):
                v = out.get(k)
                if isinstance(v, _dt):
                    out[k] = v.isoformat()
            return out

        victim_payload = {
            "canonical_name": db.get("canonical_name"),
            "type": db.get("type"),
            "aliases": list(db.get("aliases") or []),
            "summary": db.get("summary") or "",
            "properties": dict(db.get("properties") or {}),
            "is_user_edited": bool(db.get("is_user_edited")),
        }
        survivor_before = {
            "canonical_name": da.get("canonical_name"),
            "type": da.get("type"),
            "aliases": list(da.get("aliases") or []),
            "summary": da.get("summary") or "",
            "properties": dict(da.get("properties") or {}),
            "is_user_edited": bool(da.get("is_user_edited")),
        }
        victim_provenance = {"episodes": victim_episodes, "notes": victim_notes}
        incident_rel_audit = [_ser_rel(dict(r)) for r in incident_rel_rows]

        def pick(key: str) -> Any:
            return da[key] if field_selection.get(key, "survivor") == "survivor" else db[key]

        canonical = (pick("canonical_name") or "").strip()[:500] or "Unknown"
        etype = (pick("type") or "Concept").strip()[:120] or "Concept"
        aliases_m = sorted(set(da.get("aliases") or []) | set(db.get("aliases") or []))
        summary = (pick("summary") or "")[:2000]
        props_a = da.get("properties") or {}
        props_b = db.get("properties") or {}
        if field_selection.get("properties", "survivor") == "survivor":
            merged_props = {**dict(props_b), **dict(props_a)}
        else:
            merged_props = {**dict(props_a), **dict(props_b)}

        conn.execute(
            """
            UPDATE relationships SET source_entity_id = %s::uuid
            WHERE workspace_id = %s::uuid AND source_entity_id = %s::uuid
              AND target_entity_id <> %s::uuid
            """,
            (survivor_id, workspace_id, victim_id, survivor_id),
        )
        conn.execute(
            """
            UPDATE relationships SET target_entity_id = %s::uuid
            WHERE workspace_id = %s::uuid AND target_entity_id = %s::uuid
              AND source_entity_id <> %s::uuid
            """,
            (survivor_id, workspace_id, victim_id, survivor_id),
        )
        conn.execute(
            """
            UPDATE relationships SET source_entity_id = %s::uuid
            WHERE workspace_id = %s::uuid AND source_entity_id = %s::uuid
              AND target_entity_id = %s::uuid
            """,
            (survivor_id, workspace_id, victim_id, survivor_id),
        )
        conn.execute(
            """
            UPDATE relationships SET target_entity_id = %s::uuid
            WHERE workspace_id = %s::uuid AND target_entity_id = %s::uuid
              AND source_entity_id = %s::uuid
            """,
            (survivor_id, workspace_id, victim_id, survivor_id),
        )
        conn.execute(
            "DELETE FROM relationships WHERE workspace_id = %s::uuid AND source_entity_id = target_entity_id",
            (workspace_id,),
        )
        _dedupe_parallel_relationships(conn, workspace_id=workspace_id)

        conn.execute(
            """
            INSERT INTO entity_episodes (entity_id, episode_id)
            SELECT %s::uuid, episode_id FROM entity_episodes WHERE entity_id = %s::uuid
            ON CONFLICT (entity_id, episode_id) DO NOTHING
            """,
            (survivor_id, victim_id),
        )
        conn.execute(
            """
            INSERT INTO entity_notes (entity_id, note_id)
            SELECT %s::uuid, note_id FROM entity_notes WHERE entity_id = %s::uuid
            ON CONFLICT (entity_id, note_id) DO NOTHING
            """,
            (survivor_id, victim_id),
        )

        conn.execute(
            "DELETE FROM graphiti_entity_map WHERE entity_id = %s::uuid AND workspace_id = %s::uuid",
            (victim_id, workspace_id),
        )

        try:
            conn.execute(
                """
                UPDATE entities SET
                  canonical_name = %s, type = %s, aliases = %s, summary = %s,
                  properties = %s::jsonb, is_user_edited = true, updated_at = now()
                WHERE id = %s::uuid AND workspace_id = %s::uuid
                """,
                (canonical, etype, aliases_m, summary, Json(merged_props), survivor_id, workspace_id),
            )
        except pg_errors.UniqueViolation:
            conn.rollback()
            return None

        conn.execute(
            "DELETE FROM entities WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (victim_id, workspace_id),
        )

        # Best-effort audit; never block the merge on its failure (e.g. the
        # migration hasn't been applied yet on a fresh dev DB).
        try:
            insert_merge_audit(
                conn,
                workspace_id=workspace_id,
                kind="entity",
                survivor_id=survivor_id,
                victim_id=victim_id,
                victim_payload=victim_payload,
                survivor_before=survivor_before,
                victim_provenance=victim_provenance,
                incident_relationships=incident_rel_audit,
            )
        except pg_errors.UndefinedTable:
            conn.rollback()
            # Re-apply the destructive operations idempotently if the audit
            # write was the only thing that failed.
            conn.execute(
                "UPDATE entities SET canonical_name=%s, type=%s, aliases=%s, summary=%s, properties=%s::jsonb, is_user_edited=true, updated_at=now() WHERE id=%s::uuid",
                (canonical, etype, aliases_m, summary, Json(merged_props), survivor_id),
            )
            conn.execute(
                "DELETE FROM entities WHERE id = %s::uuid AND workspace_id = %s::uuid",
                (victim_id, workspace_id),
            )

        conn.commit()

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT * FROM entities WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (survivor_id, workspace_id),
        ).fetchone()
        return _serialize_entity_row(dict(row)) if row else None


def unmerge_entity(
    database_url: str,
    *,
    workspace_id: str,
    survivor_id: str,
) -> dict[str, Any] | None:
    """Restore the victim entity from the latest ``merge_audit_log`` row.

    Re-inserts the deleted entity with its original payload, re-attaches the
    provenance junctions captured at merge time, and restores any incident
    relationships whose endpoints currently point at the survivor and the
    original victim's neighbours. The survivor's own field values are also
    rolled back to ``survivor_before``.

    Returns the restored victim row, or ``None`` if no audit row exists.
    """
    from app.merge_audit_repo import fetch_latest_audit, mark_audit_undone

    audit = fetch_latest_audit(
        database_url,
        workspace_id=workspace_id,
        kind="entity",
        survivor_id=survivor_id,
    )
    if not audit:
        return None

    victim_id = str(audit["victim_id"])
    victim_payload = dict(audit["victim_payload"] or {})
    survivor_before = dict(audit["survivor_before"] or {})
    provenance = dict(audit["victim_provenance"] or {})
    incident_rels = list(audit.get("incident_relationships") or [])

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        # Re-insert the victim entity. Skip if a row with this id already
        # exists (e.g. a stale audit + a fresh entity reusing the id).
        existing = conn.execute(
            "SELECT id FROM entities WHERE id = %s::uuid",
            (victim_id,),
        ).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT INTO entities
                  (id, workspace_id, type, canonical_name, aliases, summary,
                   properties, is_user_edited, created_at, updated_at)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, %s,
                        now(), now())
                """,
                (
                    victim_id,
                    workspace_id,
                    victim_payload.get("type") or "Concept",
                    (victim_payload.get("canonical_name") or "Restored")[:500],
                    list(victim_payload.get("aliases") or []),
                    victim_payload.get("summary") or "",
                    Json(dict(victim_payload.get("properties") or {})),
                    bool(victim_payload.get("is_user_edited", False)),
                ),
            )

        # Restore provenance junctions.
        for ep_id in provenance.get("episodes") or []:
            conn.execute(
                """
                INSERT INTO entity_episodes (entity_id, episode_id)
                VALUES (%s::uuid, %s::uuid)
                ON CONFLICT DO NOTHING
                """,
                (victim_id, ep_id),
            )
        for note_id in provenance.get("notes") or []:
            conn.execute(
                """
                INSERT INTO entity_notes (entity_id, note_id)
                VALUES (%s::uuid, %s::uuid)
                ON CONFLICT DO NOTHING
                """,
                (victim_id, note_id),
            )

        # Roll back the survivor's fields. (Provenance unioned during merge
        # is left in place — the entries originated from real episodes/notes
        # and stripping them could remove valid links the user has since
        # confirmed by editing.)
        conn.execute(
            """
            UPDATE entities
            SET canonical_name = %s, type = %s, aliases = %s, summary = %s,
                properties = %s::jsonb, is_user_edited = %s, updated_at = now()
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            (
                (survivor_before.get("canonical_name") or "Unknown")[:500],
                (survivor_before.get("type") or "Concept")[:120],
                list(survivor_before.get("aliases") or []),
                survivor_before.get("summary") or "",
                Json(dict(survivor_before.get("properties") or {})),
                bool(survivor_before.get("is_user_edited", False)),
                survivor_id,
                workspace_id,
            ),
        )

        # Restore the original endpoints on relationships we audited.
        for rel in incident_rels:
            rid = str(rel.get("id"))
            src = rel.get("source_entity_id")
            tgt = rel.get("target_entity_id")
            if not rid or not src or not tgt:
                continue
            conn.execute(
                """
                UPDATE relationships
                SET source_entity_id = %s::uuid, target_entity_id = %s::uuid
                WHERE id = %s::uuid AND workspace_id = %s::uuid
                """,
                (src, tgt, rid, workspace_id),
            )

        mark_audit_undone(conn, audit_id=str(audit["id"]))
        conn.commit()

        row = conn.execute(
            "SELECT * FROM entities WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (victim_id, workspace_id),
        ).fetchone()
        return _serialize_entity_row(dict(row)) if row else None


def delete_entity(database_url: str, *, workspace_id: str, entity_id: str) -> bool:
    with psycopg.connect(database_url) as conn:
        cur = conn.execute(
            "DELETE FROM entities WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (entity_id, workspace_id),
        )
        conn.commit()
        return cur.rowcount > 0


def insert_manual_relationship(
    database_url: str,
    *,
    workspace_id: str,
    source_entity_id: str,
    target_entity_id: str,
    rel_type: str,
    fact: str = "",
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> dict[str, Any]:
    rid = str(uuid4())
    fact = (fact or "")[:500]
    rel_type = (rel_type or "RELATED_TO").strip()[:120]
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute(
            """
            INSERT INTO relationships (
              id, workspace_id, source_entity_id, target_entity_id,
              type, fact, valid_from, valid_to, confidence, origin, is_user_edited
            )
            VALUES (
              %s::uuid, %s::uuid, %s::uuid, %s::uuid,
              %s, %s, %s, %s, 1.0, 'manual', true
            )
            """,
            (rid, workspace_id, source_entity_id, target_entity_id, rel_type, fact, valid_from, valid_to),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM relationships WHERE id = %s::uuid", (rid,)).fetchone()
        assert row
        return _serialize_relationship(dict(row))


def _serialize_relationship(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for k in ("id", "workspace_id", "source_entity_id", "target_entity_id"):
        if out.get(k) is not None:
            out[k] = str(out[k])
    for k in ("valid_from", "valid_to"):
        v = out.get(k)
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    return out


def fetch_relationship(
    database_url: str, *, workspace_id: str, relationship_id: str
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT * FROM relationships
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            (relationship_id, workspace_id),
        ).fetchone()
        return _serialize_relationship(dict(row)) if row else None


def patch_relationship(
    database_url: str,
    *,
    workspace_id: str,
    relationship_id: str,
    rel_type: str | None = None,
    fact: str | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> dict[str, Any] | None:
    sets: list[str] = ["updated_at = now()", "is_user_edited = true"]
    params: list[Any] = []
    if rel_type is not None:
        sets.append("type = %s")
        params.append(rel_type.strip()[:120])
    if fact is not None:
        sets.append("fact = %s")
        params.append(fact[:500])
    if valid_from is not None:
        sets.append("valid_from = %s")
        params.append(valid_from)
    if valid_to is not None:
        sets.append("valid_to = %s")
        params.append(valid_to)
    if len(sets) <= 2:
        return fetch_relationship(database_url, workspace_id=workspace_id, relationship_id=relationship_id)
    params.extend([relationship_id, workspace_id])
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            f"""
            UPDATE relationships SET {", ".join(sets)}
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            RETURNING *
            """,
            params,
        ).fetchone()
        conn.commit()
        return _serialize_relationship(dict(row)) if row else None


def end_relationship(database_url: str, *, workspace_id: str, relationship_id: str) -> bool:
    now = datetime.now(timezone.utc)
    with psycopg.connect(database_url) as conn:
        cur = conn.execute(
            """
            UPDATE relationships SET valid_to = %s, updated_at = now(), is_user_edited = true
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            (now, relationship_id, workspace_id),
        )
        conn.commit()
        return cur.rowcount > 0
