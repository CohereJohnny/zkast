"""Sprint 6 — Postgres helpers for chat sessions, messages, and citations.

Sync psycopg style matches the rest of the ``apps/pipeline/app/*_repo.py``
modules so the worker can call these via ``asyncio.to_thread`` without a
separate connection pool.

Source of truth for column shapes: migration
[`0009_chat_tables`](../../migrations/alembic/versions/0009_chat_tables.py).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

_TITLE_MAX = 200
_CONTENT_MAX = 20_000


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def create_session(
    database_url: str,
    *,
    workspace_id: str,
    title: str = "",
    created_by_user_id: str | None = None,
    scope: dict[str, Any] | None = None,
    share_visibility: str = "private",
    model_settings: dict[str, Any] | None = None,
    pinned_snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Insert a new ``chat_sessions`` row and return it."""
    sid = str(uuid4())
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions (
                id, workspace_id, title, created_by_user_id,
                scope, share_visibility, model_settings, pinned_snapshot_id
            )
            VALUES (
                %s::uuid, %s::uuid, %s, %s,
                %s, %s, %s, %s
            )
            """,
            (
                sid,
                workspace_id,
                (title or "")[:_TITLE_MAX],
                created_by_user_id,
                Json(scope or {}),
                share_visibility,
                Json(model_settings or {}),
                pinned_snapshot_id,
            ),
        )
        conn.commit()
        return _fetch_session(conn, workspace_id=workspace_id, session_id=sid) or {}


def patch_session(
    database_url: str,
    *,
    workspace_id: str,
    session_id: str,
    title: str | None = None,
    scope: dict[str, Any] | None = None,
    model_settings: dict[str, Any] | None = None,
    pinned_snapshot_id: str | None = None,
    last_activity_at_now: bool = False,
) -> dict[str, Any] | None:
    sets: list[str] = ["updated_at = now()"]
    params: list[Any] = []
    if title is not None:
        sets.append("title = %s")
        params.append(title[:_TITLE_MAX])
    if scope is not None:
        sets.append("scope = %s")
        params.append(Json(scope))
    if model_settings is not None:
        sets.append("model_settings = %s")
        params.append(Json(model_settings))
    if pinned_snapshot_id is not None:
        sets.append("pinned_snapshot_id = %s::uuid")
        params.append(pinned_snapshot_id)
    if last_activity_at_now:
        sets.append("last_activity_at = now()")

    params.extend([workspace_id, session_id])
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        cur = conn.execute(
            f"""
            UPDATE chat_sessions
            SET {", ".join(sets)}
            WHERE workspace_id = %s::uuid AND id = %s::uuid
            RETURNING id
            """,
            params,
        )
        if cur.fetchone() is None:
            return None
        conn.commit()
        return _fetch_session(conn, workspace_id=workspace_id, session_id=session_id)


def fetch_session(
    database_url: str,
    *,
    workspace_id: str,
    session_id: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        return _fetch_session(conn, workspace_id=workspace_id, session_id=session_id)


def _fetch_session(
    conn: psycopg.Connection,
    *,
    workspace_id: str,
    session_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            id::text AS id,
            workspace_id::text AS workspace_id,
            title,
            created_by_user_id::text AS created_by_user_id,
            scope,
            share_visibility,
            model_settings,
            pinned_snapshot_id::text AS pinned_snapshot_id,
            created_at,
            updated_at,
            last_activity_at
        FROM chat_sessions
        WHERE workspace_id = %s::uuid AND id = %s::uuid
        """,
        (workspace_id, session_id),
    ).fetchone()
    if not row:
        return None
    return _serialize_session(dict(row))


def list_sessions(
    database_url: str,
    *,
    workspace_id: str,
    limit: int = 25,
    offset: int = 0,
    pinned_snapshot_id: str | None = None,
    created_by_user_id: str | None = None,
) -> dict[str, Any]:
    clauses = ["workspace_id = %s::uuid"]
    params: list[Any] = [workspace_id]
    if pinned_snapshot_id:
        clauses.append("pinned_snapshot_id = %s::uuid")
        params.append(pinned_snapshot_id)
    if created_by_user_id:
        clauses.append("created_by_user_id = %s::uuid")
        params.append(created_by_user_id)

    where = " AND ".join(clauses)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS c FROM chat_sessions WHERE {where}", params
        ).fetchone()
        total = int(total_row["c"]) if total_row else 0
        rows = conn.execute(
            f"""
            SELECT
                id::text AS id,
                workspace_id::text AS workspace_id,
                title,
                created_by_user_id::text AS created_by_user_id,
                scope,
                share_visibility,
                model_settings,
                pinned_snapshot_id::text AS pinned_snapshot_id,
                created_at,
                updated_at,
                last_activity_at
            FROM chat_sessions
            WHERE {where}
            ORDER BY last_activity_at DESC, created_at DESC
            LIMIT %s OFFSET %s
            """,
            params + [int(limit), int(offset)],
        ).fetchall()
    return {
        "items": [_serialize_session(dict(r)) for r in rows],
        "total": total,
    }


def _serialize_session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "title": row.get("title") or "",
        "created_by_user_id": row.get("created_by_user_id"),
        "scope": dict(row.get("scope") or {}),
        "share_visibility": row.get("share_visibility") or "private",
        "model_settings": dict(row.get("model_settings") or {}),
        "pinned_snapshot_id": row.get("pinned_snapshot_id"),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "last_activity_at": _iso(row.get("last_activity_at")),
    }


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    return v.isoformat()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def insert_user_message(
    database_url: str,
    *,
    session_id: str,
    content: str,
    author_user_id: str | None = None,
) -> dict[str, Any]:
    """Append a ``user`` message at the next ``sequence`` slot.

    Returns the inserted row. ``status`` is unconditionally ``complete``
    for user messages since they have no streaming lifecycle.
    """
    mid = str(uuid4())
    truncated = (content or "")[:_CONTENT_MAX]
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        seq = _next_sequence(conn, session_id=session_id)
        conn.execute(
            """
            INSERT INTO chat_messages (
                id, session_id, sequence, role, author_user_id,
                content, status, completed_at
            )
            VALUES (
                %s::uuid, %s::uuid, %s, 'user', %s,
                %s, 'complete', now()
            )
            """,
            (mid, session_id, seq, author_user_id, truncated),
        )
        # bump session last_activity_at
        conn.execute(
            "UPDATE chat_sessions SET last_activity_at = now() WHERE id = %s::uuid",
            (session_id,),
        )
        conn.commit()
        return fetch_message(database_url, message_id=mid) or {}


def insert_assistant_message_pending(
    database_url: str,
    *,
    session_id: str,
    parent_message_id: str | None,
    model_used: str | None,
    effective_scope: dict[str, Any] | None,
    retrieval_mode: str = "graph",
) -> dict[str, Any]:
    """Insert a placeholder ``assistant`` message in ``pending`` status.

    The worker will fill content + status as the turn runs.
    """
    mid = str(uuid4())
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        seq = _next_sequence(conn, session_id=session_id)
        conn.execute(
            """
            INSERT INTO chat_messages (
                id, session_id, sequence, role,
                parent_message_id, is_active_alternate,
                content, status, effective_scope_snapshot,
                model_used, retrieval_mode
            )
            VALUES (
                %s::uuid, %s::uuid, %s, 'assistant',
                %s, true,
                '', 'pending', %s,
                %s, %s
            )
            """,
            (
                mid,
                session_id,
                seq,
                parent_message_id,
                Json(effective_scope) if effective_scope is not None else None,
                model_used,
                retrieval_mode,
            ),
        )
        conn.commit()
        return fetch_message(database_url, message_id=mid) or {}


def _next_sequence(conn: psycopg.Connection, *, session_id: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(sequence), -1) + 1 AS next_seq
        FROM chat_messages
        WHERE session_id = %s::uuid
        """,
        (session_id,),
    ).fetchone()
    return int(row["next_seq"]) if row else 0


def update_assistant_message(
    database_url: str,
    *,
    message_id: str,
    content: str | None = None,
    status: str | None = None,
    failure_reason: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    completed_now: bool = False,
) -> None:
    sets: list[str] = []
    params: list[Any] = []
    if content is not None:
        sets.append("content = %s")
        params.append(content[:_CONTENT_MAX])
    if status is not None:
        sets.append("status = %s")
        params.append(status)
    if failure_reason is not None:
        sets.append("failure_reason = %s")
        params.append(failure_reason[:500])
    if tokens_in is not None:
        sets.append("tokens_in = %s")
        params.append(int(tokens_in))
    if tokens_out is not None:
        sets.append("tokens_out = %s")
        params.append(int(tokens_out))
    if completed_now:
        sets.append("completed_at = now()")

    if not sets:
        return

    params.append(message_id)
    with psycopg.connect(database_url) as conn:
        conn.execute(
            f"""
            UPDATE chat_messages
            SET {", ".join(sets)}
            WHERE id = %s::uuid
            """,
            params,
        )
        conn.commit()


def fetch_message(
    database_url: str,
    *,
    message_id: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT
                id::text AS id,
                session_id::text AS session_id,
                sequence,
                role,
                parent_message_id::text AS parent_message_id,
                is_active_alternate,
                author_user_id::text AS author_user_id,
                content,
                status,
                failure_reason,
                effective_scope_snapshot,
                model_used,
                tokens_in,
                tokens_out,
                retrieval_mode,
                created_at,
                completed_at
            FROM chat_messages
            WHERE id = %s::uuid
            """,
            (message_id,),
        ).fetchone()
    if not row:
        return None
    return _serialize_message(dict(row))


def list_messages_for_session(
    database_url: str,
    *,
    session_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
                id::text AS id,
                session_id::text AS session_id,
                sequence,
                role,
                parent_message_id::text AS parent_message_id,
                is_active_alternate,
                author_user_id::text AS author_user_id,
                content,
                status,
                failure_reason,
                effective_scope_snapshot,
                model_used,
                tokens_in,
                tokens_out,
                retrieval_mode,
                created_at,
                completed_at
            FROM chat_messages
            WHERE session_id = %s::uuid
            ORDER BY sequence ASC, created_at ASC
            LIMIT %s
            """,
            (session_id, int(limit)),
        ).fetchall()
    return [_serialize_message(dict(r)) for r in rows]


def _serialize_message(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "sequence": int(row["sequence"]),
        "role": row["role"],
        "parent_message_id": row.get("parent_message_id"),
        "is_active_alternate": bool(row.get("is_active_alternate")),
        "author_user_id": row.get("author_user_id"),
        "content": row.get("content") or "",
        "status": row.get("status") or "pending",
        "failure_reason": row.get("failure_reason"),
        "effective_scope_snapshot": (
            dict(row["effective_scope_snapshot"])
            if row.get("effective_scope_snapshot") is not None
            else None
        ),
        "model_used": row.get("model_used"),
        "tokens_in": row.get("tokens_in"),
        "tokens_out": row.get("tokens_out"),
        "retrieval_mode": row.get("retrieval_mode") or "graph",
        "created_at": _iso(row.get("created_at")),
        "completed_at": _iso(row.get("completed_at")),
    }


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------


def insert_citation_rows(
    database_url: str,
    *,
    message_id: str,
    rows: list[dict[str, Any]],
) -> int:
    """Bulk-insert ``chat_citations`` rows. Returns inserted count.

    Each row dict: ``{"text_start": int, "text_end": int, "sources": [...]}``.
    """
    if not rows:
        return 0
    inserted = 0
    with psycopg.connect(database_url) as conn:
        for r in rows:
            ts = int(r["text_start"])
            te = int(r["text_end"])
            if te <= ts:
                continue
            conn.execute(
                """
                INSERT INTO chat_citations (
                    id, message_id, text_start, text_end, sources
                )
                VALUES (
                    %s::uuid, %s::uuid, %s, %s, %s
                )
                """,
                (
                    str(uuid4()),
                    message_id,
                    ts,
                    te,
                    Json(r.get("sources") or []),
                ),
            )
            inserted += 1
        conn.commit()
    return inserted


def list_citations_for_message(
    database_url: str,
    *,
    message_id: str,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
                id::text AS id,
                message_id::text AS message_id,
                text_start,
                text_end,
                sources,
                created_at
            FROM chat_citations
            WHERE message_id = %s::uuid
            ORDER BY text_start ASC
            """,
            (message_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "message_id": r["message_id"],
            "text_start": int(r["text_start"]),
            "text_end": int(r["text_end"]),
            "sources": list(r["sources"] or []),
            "created_at": _iso(r["created_at"]),
        }
        for r in rows
    ]
