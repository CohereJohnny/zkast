"""Atomic notes and note_links (sync psycopg)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def _norm_tags(tags: list[str]) -> list[str]:
    return sorted({t.strip().lower() for t in tags if t and t.strip()})


def clear_notes_for_ingestion_run(database_url: str, *, ingestion_run_id: str) -> int:
    """Drop episode links for this run's episodes; delete notes that end up with no episodes."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        touched = conn.execute(
            """
            SELECT DISTINCT ne.note_id
            FROM note_episodes ne
            JOIN episodes e ON e.id = ne.episode_id
            WHERE e.ingestion_run_id = %s::uuid
            """,
            (ingestion_run_id,),
        ).fetchall()
        touched_ids = [str(r["note_id"]) for r in touched]
        conn.execute(
            """
            DELETE FROM note_episodes
            WHERE episode_id IN (SELECT id FROM episodes WHERE ingestion_run_id = %s::uuid)
            """,
            (ingestion_run_id,),
        )
        deleted = 0
        for nid in touched_ids:
            cur = conn.execute(
                """
                DELETE FROM atomic_notes
                WHERE id = %s::uuid
                  AND NOT EXISTS (SELECT 1 FROM note_episodes ne WHERE ne.note_id = %s::uuid)
                """,
                (nid, nid),
            )
            deleted += cur.rowcount or 0
        conn.commit()
        return deleted


def clear_notes_for_episode_ids(database_url: str, *, episode_ids: list[str]) -> int:
    """Remove provenance rows for given episodes; delete notes left without any episode."""
    if not episode_ids:
        return 0
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        touched = conn.execute(
            """
            SELECT DISTINCT ne.note_id
            FROM note_episodes ne
            WHERE ne.episode_id = ANY(%s::uuid[])
            """,
            (episode_ids,),
        ).fetchall()
        touched_ids = [str(r["note_id"]) for r in touched]
        conn.execute(
            "DELETE FROM note_episodes WHERE episode_id = ANY(%s::uuid[])",
            (episode_ids,),
        )
        deleted = 0
        for nid in touched_ids:
            cur = conn.execute(
                """
                DELETE FROM atomic_notes
                WHERE id = %s::uuid
                  AND NOT EXISTS (SELECT 1 FROM note_episodes ne WHERE ne.note_id = %s::uuid)
                """,
                (nid, nid),
            )
            deleted += cur.rowcount or 0
        conn.commit()
        return deleted


def list_note_ids_for_document(
    database_url: str,
    *,
    workspace_id: str,
    document_id: str,
) -> list[str]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT n.id::text AS id
            FROM atomic_notes n
            JOIN note_episodes ne ON ne.note_id = n.id
            JOIN episodes e ON e.id = ne.episode_id
            WHERE n.workspace_id = %s::uuid AND e.document_id = %s::uuid
            ORDER BY id
            """,
            (workspace_id, document_id),
        ).fetchall()
        return [r["id"] for r in rows]


def insert_note(
    database_url: str,
    *,
    note_id: str,
    workspace_id: str,
    title: str,
    body: str,
    tags: list[str],
    origin: str,
    created_by_user_id: str | None = None,
    episode_ids: list[str] | None = None,
    is_user_edited: bool = False,
    agent_id: str | None = None,
    memory_context: str | None = None,
    memory_keywords: list[str] | None = None,
) -> dict[str, Any]:
    tags_n = _norm_tags(tags)
    kws = sorted({k.strip().lower() for k in (memory_keywords or []) if k and k.strip()})[:40]
    ep_ids = episode_ids or []
    if origin == "generated" and not ep_ids:
        raise ValueError("generated notes require at least one source episode")
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute(
            """
            INSERT INTO atomic_notes (
              id, workspace_id, title, body, tags, origin,
              is_user_edited, created_by_user_id, agent_id,
              memory_context, memory_keywords
            )
            VALUES (
              %s::uuid, %s::uuid, %s, %s, %s, %s, %s,
              CAST(%s AS uuid), %s::uuid, %s, %s::text[]
            )
            """,
            (
                note_id,
                workspace_id,
                title[:200],
                body[:10000],
                tags_n,
                origin,
                is_user_edited,
                created_by_user_id,
                agent_id,
                memory_context[:2000] if memory_context else None,
                kws,
            ),
        )
        for eid in ep_ids:
            conn.execute(
                """
                INSERT INTO note_episodes (note_id, episode_id)
                VALUES (%s::uuid, %s::uuid)
                ON CONFLICT (note_id, episode_id) DO NOTHING
                """,
                (note_id, eid),
            )
        conn.commit()
    return fetch_note(database_url, workspace_id=workspace_id, note_id=note_id) or {}


def fetch_note(database_url: str, *, workspace_id: str, note_id: str) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT * FROM atomic_notes
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            LIMIT 1
            """,
            (note_id, workspace_id),
        ).fetchone()
        if not row:
            return None
        return _serialize_note_row(dict(row))


def fetch_note_detail(database_url: str, *, workspace_id: str, note_id: str) -> dict[str, Any] | None:
    base = fetch_note(database_url, workspace_id=workspace_id, note_id=note_id)
    if not base:
        return None
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        links_out = conn.execute(
            """
            SELECT id::text, target_note_id::text, kind, custom_label, origin,
                   link_reason, link_strength, created_at
            FROM note_links
            WHERE workspace_id = %s::uuid AND source_note_id = %s::uuid
            ORDER BY created_at ASC
            """,
            (workspace_id, note_id),
        ).fetchall()
        links_in = conn.execute(
            """
            SELECT id::text, source_note_id::text, kind, custom_label, origin,
                   link_reason, link_strength, created_at
            FROM note_links
            WHERE workspace_id = %s::uuid AND target_note_id = %s::uuid
            ORDER BY created_at ASC
            """,
            (workspace_id, note_id),
        ).fetchall()
        eps = conn.execute(
            """
            SELECT e.id::text, e.document_id::text, e.page_start, e.page_end, e.sequence
            FROM episodes e
            INNER JOIN note_episodes ne ON ne.episode_id = e.id
            WHERE ne.note_id = %s::uuid
            ORDER BY e.sequence ASC
            """,
            (note_id,),
        ).fetchall()
    return {
        **base,
        "links_out": [dict(r) for r in links_out],
        "links_in": [dict(r) for r in links_in],
        "source_episodes": [dict(r) for r in eps],
    }


def _serialize_note_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["id"] = str(out["id"])
    out["workspace_id"] = str(out["workspace_id"])
    if out.get("created_by_user_id"):
        out["created_by_user_id"] = str(out["created_by_user_id"])
    if out.get("agent_id"):
        out["agent_id"] = str(out["agent_id"])
    for k in ("created_at", "updated_at", "dreaming_touched_at"):
        if out.get(k) and hasattr(out[k], "isoformat"):
            out[k] = out[k].isoformat()
    return out


def list_notes(
    database_url: str,
    *,
    workspace_id: str,
    q: str | None = None,
    tags: list[str] | None = None,
    document_id: str | None = None,
    origin: str | None = None,
    is_user_edited: bool | None = None,
    agent_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    sort: str = "updated_at_desc",
) -> tuple[list[dict[str, Any]], int]:
    where = ["n.workspace_id = %s::uuid"]
    params: list[Any] = [workspace_id]
    if q and q.strip():
        where.append(
            "to_tsvector('english', coalesce(n.title,'') || ' ' || coalesce(n.body,'')) "
            "@@ plainto_tsquery('english', %s)",
        )
        params.append(q.strip())
    if tags:
        where.append("n.tags && %s::text[]")
        params.append(_norm_tags(tags))
    if document_id:
        where.append(
            "EXISTS (SELECT 1 FROM note_episodes ne "
            "JOIN episodes e ON e.id = ne.episode_id "
            "WHERE ne.note_id = n.id AND e.document_id = %s::uuid)",
        )
        params.append(document_id)
    if origin:
        where.append("n.origin = %s")
        params.append(origin)
    if is_user_edited is not None:
        where.append("n.is_user_edited = %s")
        params.append(is_user_edited)
    if agent_id:
        where.append("n.agent_id = %s::uuid")
        params.append(agent_id)

    order = "n.updated_at DESC"
    if sort == "created_at_desc":
        order = "n.created_at DESC"
    elif sort == "title_asc":
        order = "n.title ASC"

    where_sql = " AND ".join(where)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        total = conn.execute(
            f"SELECT count(*)::int AS c FROM atomic_notes n WHERE {where_sql}",
            params,
        ).fetchone()["c"]
        rows = conn.execute(
            f"""
            SELECT n.id, n.workspace_id, n.title, n.body, n.tags, n.origin,
                   n.is_user_edited, n.created_at, n.updated_at,
                   n.agent_id, n.memory_context, n.memory_keywords,
                   n.evolution_history, n.dreaming_touched_at
            FROM atomic_notes n
            WHERE {where_sql}
            ORDER BY {order}
            LIMIT %s OFFSET %s
            """,
            [*params, limit, offset],
        ).fetchall()
    out = [_serialize_note_row(dict(r)) for r in rows]
    return out, int(total)


def update_note(
    database_url: str,
    *,
    workspace_id: str,
    note_id: str,
    title: str | None = None,
    body: str | None = None,
    tags: list[str] | None = None,
    mark_user_edited: bool = True,
) -> dict[str, Any] | None:
    sets: list[str] = []
    params: list[Any] = []
    if title is not None:
        sets.append("title = %s")
        params.append(title[:200])
    if body is not None:
        sets.append("body = %s")
        params.append(body[:10000])
    if tags is not None:
        sets.append("tags = %s")
        params.append(_norm_tags(tags))
    if mark_user_edited:
        sets.append("is_user_edited = true")
    if not sets:
        return fetch_note(database_url, workspace_id=workspace_id, note_id=note_id)
    sets.append("updated_at = now()")
    params.extend([note_id, workspace_id])
    with psycopg.connect(database_url) as conn:
        conn.execute(
            f"""
            UPDATE atomic_notes SET {", ".join(sets)}
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            params,
        )
        conn.commit()
    return fetch_note(database_url, workspace_id=workspace_id, note_id=note_id)


def append_evolution_history(
    database_url: str,
    *,
    workspace_id: str,
    note_id: str,
    entry: dict[str, Any],
) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT evolution_history FROM atomic_notes
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            (note_id, workspace_id),
        ).fetchone()
        if not row:
            return
        hist = list(row["evolution_history"] or [])
        hist.append(entry)
        conn.execute(
            """
            UPDATE atomic_notes
            SET evolution_history = %s::jsonb,
                dreaming_touched_at = now(),
                updated_at = now()
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            (Json(hist), note_id, workspace_id),
        )
        conn.commit()


def patch_note_derivations(
    database_url: str,
    *,
    workspace_id: str,
    note_id: str,
    memory_context: str | None = None,
    memory_keywords: list[str] | None = None,
    tags: list[str] | None = None,
) -> None:
    """Update derived A-MEM / dreaming fields without marking user-edited."""
    sets: list[str] = []
    params: list[Any] = []
    if memory_context is not None:
        sets.append("memory_context = %s")
        params.append(memory_context[:2000])
    if memory_keywords is not None:
        sets.append("memory_keywords = %s")
        params.append(sorted({k.strip().lower() for k in memory_keywords if k and k.strip()})[:40])
    if tags is not None:
        sets.append("tags = %s")
        params.append(_norm_tags(tags))
    if not sets:
        return
    sets.append("dreaming_touched_at = now()")
    sets.append("updated_at = now()")
    params.extend([note_id, workspace_id])
    with psycopg.connect(database_url) as conn:
        conn.execute(
            f"""
            UPDATE atomic_notes SET {", ".join(sets)}
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            params,
        )
        conn.commit()


def delete_note(database_url: str, *, workspace_id: str, note_id: str) -> bool:
    with psycopg.connect(database_url) as conn:
        cur = conn.execute(
            """
            DELETE FROM atomic_notes
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            (note_id, workspace_id),
        )
        conn.commit()
        return cur.rowcount > 0


def add_note_link(
    database_url: str,
    *,
    workspace_id: str,
    source_note_id: str,
    target_note_id: str,
    kind: str,
    custom_label: str | None,
    origin: str,
    link_reason: str | None = None,
    link_strength: float = 1.0,
) -> dict[str, Any]:
    if source_note_id == target_note_id:
        raise ValueError("cannot link note to itself")
    if kind == "custom" and not (custom_label and custom_label.strip()):
        raise ValueError("custom_label required for kind=custom")
    lid = str(uuid4())
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        ra = conn.execute(
            "SELECT agent_id FROM atomic_notes WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (source_note_id, workspace_id),
        ).fetchone()
        rb = conn.execute(
            "SELECT agent_id FROM atomic_notes WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (target_note_id, workspace_id),
        ).fetchone()
        if not ra or not rb:
            raise ValueError("note not found for link")
        aid_a, aid_b = ra["agent_id"], rb["agent_id"]
        if aid_a is not None and aid_b is not None and str(aid_a) != str(aid_b):
            raise ValueError("cross_agent_link_forbidden")
        conn.execute(
            """
            INSERT INTO note_links (
              id, workspace_id, source_note_id, target_note_id, kind, custom_label, origin,
              link_reason, link_strength
            )
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s)
            """,
            (
                lid,
                workspace_id,
                source_note_id,
                target_note_id,
                kind,
                custom_label.strip() if custom_label else None,
                origin,
                link_reason[:2000] if link_reason else None,
                float(link_strength),
            ),
        )
        conn.commit()
    return {"id": lid}


def delete_note_link(database_url: str, *, workspace_id: str, link_id: str) -> bool:
    with psycopg.connect(database_url) as conn:
        cur = conn.execute(
            """
            DELETE FROM note_links
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            (link_id, workspace_id),
        )
        conn.commit()
        return cur.rowcount > 0


def union_note_episodes(database_url: str, conn: psycopg.Connection, survivor_id: str, other_id: str) -> None:
    rows = conn.execute(
        "SELECT episode_id FROM note_episodes WHERE note_id = %s::uuid",
        (other_id,),
    ).fetchall()
    for r in rows:
        conn.execute(
            """
            INSERT INTO note_episodes (note_id, episode_id)
            VALUES (%s::uuid, %s::uuid)
            ON CONFLICT (note_id, episode_id) DO NOTHING
            """,
            (survivor_id, r["episode_id"]),
        )


def rewrite_links_for_merge(database_url: str, conn: psycopg.Connection, survivor_id: str, other_id: str) -> None:
    conn.execute(
        """
        UPDATE note_links SET source_note_id = %s::uuid
        WHERE source_note_id = %s::uuid AND target_note_id <> %s::uuid
        """,
        (survivor_id, other_id, survivor_id),
    )
    conn.execute(
        """
        UPDATE note_links SET target_note_id = %s::uuid
        WHERE target_note_id = %s::uuid AND source_note_id <> %s::uuid
        """,
        (survivor_id, other_id, survivor_id),
    )
    conn.execute("DELETE FROM note_links WHERE source_note_id = %s::uuid OR target_note_id = %s::uuid", (other_id, other_id))


def merge_notes(
    database_url: str,
    *,
    workspace_id: str,
    survivor_note_id: str,
    other_note_id: str,
    field_selection: dict[str, str],
) -> dict[str, Any] | None:
    """field_selection keys: title, body, tags — values 'survivor' | 'other'.

    Sprint 5b: writes a ``merge_audit_log`` row capturing victim payload +
    survivor pre-merge fields + victim's episode provenance so
    :func:`unmerge_note` can restore everything.
    """
    from app.merge_audit_repo import insert_merge_audit
    from psycopg import errors as pg_errors

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        a = conn.execute(
            "SELECT * FROM atomic_notes WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (survivor_note_id, workspace_id),
        ).fetchone()
        b = conn.execute(
            "SELECT * FROM atomic_notes WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (other_note_id, workspace_id),
        ).fetchone()
        if not a or not b:
            return None
        da, db = dict(a), dict(b)
        title = da["title"] if field_selection.get("title", "survivor") == "survivor" else db["title"]
        body = da["body"] if field_selection.get("body", "survivor") == "survivor" else db["body"]
        tags_src = list(da.get("tags") or []) if field_selection.get("tags", "survivor") == "survivor" else list(db.get("tags") or [])
        tags_other = list(db.get("tags") or []) if field_selection.get("tags", "survivor") == "survivor" else list(da.get("tags") or [])
        merged_tags = sorted(set(tags_src) | set(tags_other))

        # Snapshot the victim + survivor state for unmerge.
        victim_episodes = [
            str(r["episode_id"])
            for r in conn.execute(
                "SELECT episode_id FROM note_episodes WHERE note_id = %s::uuid",
                (other_note_id,),
            ).fetchall()
        ]
        victim_payload = {
            "title": db.get("title"),
            "body": db.get("body"),
            "tags": list(db.get("tags") or []),
            "origin": db.get("origin"),
            "is_user_edited": bool(db.get("is_user_edited")),
        }
        survivor_before = {
            "title": da.get("title"),
            "body": da.get("body"),
            "tags": list(da.get("tags") or []),
            "origin": da.get("origin"),
            "is_user_edited": bool(da.get("is_user_edited")),
        }
        victim_provenance = {"episodes": victim_episodes}

        union_note_episodes(database_url, conn, survivor_note_id, other_note_id)
        rewrite_links_for_merge(database_url, conn, survivor_note_id, other_note_id)

        conn.execute(
            """
            UPDATE atomic_notes
            SET title = %s, body = %s, tags = %s, origin = 'merged',
                is_user_edited = true, updated_at = now()
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            (title[:200], body[:10000], merged_tags, survivor_note_id, workspace_id),
        )
        conn.execute(
            "DELETE FROM atomic_notes WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (other_note_id, workspace_id),
        )
        try:
            insert_merge_audit(
                conn,
                workspace_id=workspace_id,
                kind="note",
                survivor_id=survivor_note_id,
                victim_id=other_note_id,
                victim_payload=victim_payload,
                survivor_before=survivor_before,
                victim_provenance=victim_provenance,
            )
        except pg_errors.UndefinedTable:
            # merge_audit_log not yet migrated; merge still succeeds, unmerge
            # just isn't available for this row.
            pass

        conn.commit()
    return fetch_note(database_url, workspace_id=workspace_id, note_id=survivor_note_id)


def unmerge_note(
    database_url: str,
    *,
    workspace_id: str,
    survivor_note_id: str,
) -> dict[str, Any] | None:
    """Restore a merge victim note from its audit row."""
    from app.merge_audit_repo import fetch_latest_audit, mark_audit_undone

    audit = fetch_latest_audit(
        database_url,
        workspace_id=workspace_id,
        kind="note",
        survivor_id=survivor_note_id,
    )
    if not audit:
        return None

    victim_id = str(audit["victim_id"])
    victim_payload = dict(audit["victim_payload"] or {})
    survivor_before = dict(audit["survivor_before"] or {})
    provenance = dict(audit["victim_provenance"] or {})

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        existing = conn.execute(
            "SELECT id FROM atomic_notes WHERE id = %s::uuid",
            (victim_id,),
        ).fetchone()
        if not existing:
            conn.execute(
                """
                INSERT INTO atomic_notes
                  (id, workspace_id, title, body, tags, origin,
                   is_user_edited, created_at, updated_at)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, now(), now())
                """,
                (
                    victim_id,
                    workspace_id,
                    (victim_payload.get("title") or "Restored note")[:200],
                    (victim_payload.get("body") or "")[:10000],
                    list(victim_payload.get("tags") or []),
                    (victim_payload.get("origin") or "manual"),
                    bool(victim_payload.get("is_user_edited", False)),
                ),
            )
        for ep_id in provenance.get("episodes") or []:
            conn.execute(
                """
                INSERT INTO note_episodes (note_id, episode_id)
                VALUES (%s::uuid, %s::uuid)
                ON CONFLICT DO NOTHING
                """,
                (victim_id, ep_id),
            )

        conn.execute(
            """
            UPDATE atomic_notes
            SET title = %s, body = %s, tags = %s, origin = %s,
                is_user_edited = %s, updated_at = now()
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            (
                (survivor_before.get("title") or "")[:200],
                (survivor_before.get("body") or "")[:10000],
                list(survivor_before.get("tags") or []),
                survivor_before.get("origin") or "manual",
                bool(survivor_before.get("is_user_edited", False)),
                survivor_note_id,
                workspace_id,
            ),
        )

        mark_audit_undone(conn, audit_id=str(audit["id"]))
        conn.commit()

        row = conn.execute(
            "SELECT * FROM atomic_notes WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (victim_id, workspace_id),
        ).fetchone()
        return _serialize_note_row(dict(row)) if row else None


def split_note(
    database_url: str,
    *,
    workspace_id: str,
    parent_note_id: str,
    passage: str,
    new_title: str,
    bypass_user_id: str | None,
) -> dict[str, Any]:
    passage = passage.strip()
    if not passage:
        raise ValueError("passage required")
    parent = fetch_note(database_url, workspace_id=workspace_id, note_id=parent_note_id)
    if not parent:
        raise ValueError("parent not found")
    body = parent["body"]
    if passage not in body:
        raise ValueError("passage must appear verbatim in parent body")
    new_id = str(uuid4())
    remainder = body.replace(passage, "", 1).strip()
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute(
            """
            INSERT INTO atomic_notes (
              id, workspace_id, title, body, tags, origin,
              is_user_edited, created_by_user_id
            )
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, 'split', true, %s)
            """,
            (
                new_id,
                workspace_id,
                new_title[:200],
                passage[:10000],
                parent.get("tags") or [],
                bypass_user_id,
            ),
        )
        for ep_row in conn.execute(
            "SELECT episode_id FROM note_episodes WHERE note_id = %s::uuid",
            (parent_note_id,),
        ).fetchall():
            conn.execute(
                """
                INSERT INTO note_episodes (note_id, episode_id)
                VALUES (%s::uuid, %s::uuid)
                ON CONFLICT (note_id, episode_id) DO NOTHING
                """,
                (new_id, ep_row["episode_id"]),
            )
        conn.execute(
            """
            UPDATE atomic_notes SET body = %s, is_user_edited = true, updated_at = now()
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            """,
            (remainder[:10000], parent_note_id, workspace_id),
        )
        lid = str(uuid4())
        conn.execute(
            """
            INSERT INTO note_links (
              id, workspace_id, source_note_id, target_note_id, kind, custom_label, origin
            )
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, 'extends', NULL, 'generated')
            """,
            (lid, workspace_id, parent_note_id, new_id),
        )
        conn.commit()
    return fetch_note(database_url, workspace_id=workspace_id, note_id=new_id) or {}
