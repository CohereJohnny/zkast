"""CRUD and queries for LLM Wiki memory tables.

Mirrors the patterns established in ``north_repo.py``: thin psycopg helpers that
do explicit ``uuid::text`` / ``timestamptz::isoformat`` normalisation so the
internal HTTP layer can ``json.dumps`` rows without further conversion.

See ``specs/openspecs/llm-wiki-memory.md`` for the data-model authority.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


# ---------------------------------------------------------------------------
# Wiki Space
# ---------------------------------------------------------------------------


def insert_wiki_space(
    database_url: str,
    *,
    workspace_id: str,
    name: str,
    scope_kind: str = "workspace",
    agent_id: str | None = None,
    scope_target_id: str | None = None,
    settings: dict[str, Any] | None = None,
) -> str:
    space_id = str(uuid4())
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO wiki_spaces (
              id, workspace_id, agent_id, scope_kind, scope_target_id,
              name, status, settings
            )
            VALUES (
              %s::uuid, %s::uuid, %s::uuid, %s, %s::uuid,
              %s, 'empty', %s::jsonb
            )
            """,
            (
                space_id,
                workspace_id,
                agent_id,
                scope_kind,
                scope_target_id,
                name,
                Json(settings or {}),
            ),
        )
        conn.commit()
    return space_id


def upsert_default_wiki_space(
    database_url: str,
    *,
    workspace_id: str,
    name: str | None = None,
) -> dict[str, Any]:
    """Return (or create) the workspace-wide wiki space for a workspace."""
    existing = fetch_wiki_space_by_scope(
        database_url,
        workspace_id=workspace_id,
        scope_kind="workspace",
        scope_target_id=None,
    )
    if existing:
        return existing
    label = name or "Workspace wiki"
    insert_wiki_space(
        database_url,
        workspace_id=workspace_id,
        name=label,
        scope_kind="workspace",
    )
    return fetch_wiki_space_by_scope(
        database_url,
        workspace_id=workspace_id,
        scope_kind="workspace",
        scope_target_id=None,
    ) or {}


def upsert_agent_wiki_space(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str,
    name: str | None = None,
) -> dict[str, Any]:
    existing = fetch_wiki_space_by_scope(
        database_url,
        workspace_id=workspace_id,
        scope_kind="agent",
        scope_target_id=agent_id,
    )
    if existing:
        return existing
    label = name or f"Agent wiki {agent_id[:8]}"
    insert_wiki_space(
        database_url,
        workspace_id=workspace_id,
        name=label,
        scope_kind="agent",
        agent_id=agent_id,
        scope_target_id=agent_id,
    )
    return fetch_wiki_space_by_scope(
        database_url,
        workspace_id=workspace_id,
        scope_kind="agent",
        scope_target_id=agent_id,
    ) or {}


def update_wiki_space_status(
    database_url: str,
    *,
    space_id: str,
    status: str,
    mark_generated: bool = False,
) -> None:
    sets = ["status = %s", "updated_at = now()"]
    params: list[Any] = [status]
    if mark_generated:
        sets.append("last_generated_at = now()")
    params.append(space_id)
    with psycopg.connect(database_url) as conn:
        conn.execute(
            f"UPDATE wiki_spaces SET {', '.join(sets)} WHERE id = %s::uuid",
            tuple(params),
        )
        conn.commit()


def list_wiki_spaces(
    database_url: str,
    *,
    workspace_id: str,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
              ws.id, ws.workspace_id, ws.agent_id, ws.scope_kind,
              ws.scope_target_id, ws.name, ws.status, ws.settings,
              ws.last_generated_at, ws.created_at, ws.updated_at,
              (SELECT COUNT(*) FROM wiki_pages wp WHERE wp.wiki_space_id = ws.id) AS page_count
            FROM wiki_spaces ws
            WHERE ws.workspace_id = %s::uuid
            ORDER BY ws.created_at ASC
            """,
            (workspace_id,),
        ).fetchall()
    return [_serialize_space_row(dict(r)) for r in rows]


def fetch_wiki_space(
    database_url: str,
    *,
    workspace_id: str,
    space_id: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT
              id, workspace_id, agent_id, scope_kind, scope_target_id,
              name, status, settings, last_generated_at, created_at, updated_at
            FROM wiki_spaces
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            LIMIT 1
            """,
            (space_id, workspace_id),
        ).fetchone()
    if not row:
        return None
    return _serialize_space_row(dict(row))


def fetch_wiki_space_by_scope(
    database_url: str,
    *,
    workspace_id: str,
    scope_kind: str,
    scope_target_id: str | None,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT
              id, workspace_id, agent_id, scope_kind, scope_target_id,
              name, status, settings, last_generated_at, created_at, updated_at
            FROM wiki_spaces
            WHERE workspace_id = %s::uuid
              AND scope_kind = %s
              AND scope_target_id IS NOT DISTINCT FROM %s::uuid
            LIMIT 1
            """,
            (workspace_id, scope_kind, scope_target_id),
        ).fetchone()
    if not row:
        return None
    return _serialize_space_row(dict(row))


def _serialize_space_row(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row)
    for key in ("id", "workspace_id", "agent_id", "scope_target_id"):
        if r.get(key) is not None:
            r[key] = str(r[key])
    for ts in ("last_generated_at", "created_at", "updated_at"):
        v = r.get(ts)
        if v is not None and hasattr(v, "isoformat"):
            r[ts] = v.isoformat()
    return r


# ---------------------------------------------------------------------------
# Wiki Page
# ---------------------------------------------------------------------------


SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, fallback: str = "page") -> str:
    base = SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return base[:80] if base else fallback


def upsert_wiki_page(
    database_url: str,
    *,
    wiki_space_id: str,
    slug: str,
    title: str,
    page_type: str,
    body: str,
    summary: str | None = None,
    status: str = "ready",
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Insert or update a wiki page; returns (page_id, action) where action is
    ``"created"`` or ``"updated"``.
    """
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        existing = conn.execute(
            "SELECT id FROM wiki_pages WHERE wiki_space_id = %s::uuid AND slug = %s LIMIT 1",
            (wiki_space_id, slug),
        ).fetchone()
        if existing:
            page_id = str(existing["id"])
            conn.execute(
                """
                UPDATE wiki_pages
                SET title = %s,
                    page_type = %s,
                    body = %s,
                    summary = %s,
                    status = %s,
                    confidence = %s,
                    metadata = %s::jsonb,
                    updated_at = now()
                WHERE id = %s::uuid
                """,
                (
                    title,
                    page_type,
                    body,
                    summary,
                    status,
                    confidence,
                    Json(metadata or {}),
                    page_id,
                ),
            )
            conn.commit()
            return page_id, "updated"
        page_id = str(uuid4())
        conn.execute(
            """
            INSERT INTO wiki_pages (
              id, wiki_space_id, slug, title, page_type, body, summary,
              status, confidence, metadata
            )
            VALUES (
              %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
            )
            """,
            (
                page_id,
                wiki_space_id,
                slug,
                title,
                page_type,
                body,
                summary,
                status,
                confidence,
                Json(metadata or {}),
            ),
        )
        conn.commit()
        return page_id, "created"


def list_wiki_pages(
    database_url: str,
    *,
    wiki_space_id: str,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
              id, wiki_space_id, slug, title, page_type, summary, status,
              confidence, metadata, created_at, updated_at
            FROM wiki_pages
            WHERE wiki_space_id = %s::uuid
            ORDER BY
              CASE page_type
                WHEN 'index' THEN 0
                WHEN 'changelog' THEN 1
                WHEN 'synthesis' THEN 2
                WHEN 'topic' THEN 3
                WHEN 'entity' THEN 4
                WHEN 'comparison' THEN 5
                WHEN 'source_summary' THEN 6
                ELSE 7
              END,
              title ASC
            """,
            (wiki_space_id,),
        ).fetchall()
    return [_serialize_page_row(dict(r)) for r in rows]


def fetch_wiki_page(
    database_url: str,
    *,
    wiki_space_id: str,
    slug: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT
              id, wiki_space_id, slug, title, page_type, body, summary,
              status, confidence, metadata, created_at, updated_at
            FROM wiki_pages
            WHERE wiki_space_id = %s::uuid AND slug = %s
            LIMIT 1
            """,
            (wiki_space_id, slug),
        ).fetchone()
    if not row:
        return None
    return _serialize_page_row(dict(row))


def fetch_wiki_page_sources(
    database_url: str,
    *,
    wiki_page_id: str,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT id, wiki_page_id, source_kind, source_id, quote, weight, created_at
            FROM wiki_page_sources
            WHERE wiki_page_id = %s::uuid
            ORDER BY created_at ASC
            """,
            (wiki_page_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for k in ("id", "wiki_page_id"):
            if d.get(k) is not None:
                d[k] = str(d[k])
        if hasattr(d.get("created_at"), "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    return out


def replace_wiki_page_sources(
    database_url: str,
    *,
    wiki_page_id: str,
    sources: list[dict[str, Any]],
) -> int:
    """Replace the citation rows for a page. ``sources`` items have
    ``source_kind``, ``source_id`` (str), optional ``quote`` and ``weight``.
    Returns the number of inserted rows.
    """
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "DELETE FROM wiki_page_sources WHERE wiki_page_id = %s::uuid",
            (wiki_page_id,),
        )
        inserted = 0
        for s in sources:
            sid = str(s.get("source_id") or "").strip()
            kind = str(s.get("source_kind") or "").strip()
            if not sid or not kind:
                continue
            conn.execute(
                """
                INSERT INTO wiki_page_sources (
                  id, wiki_page_id, source_kind, source_id, quote, weight
                )
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s)
                """,
                (
                    str(uuid4()),
                    wiki_page_id,
                    kind,
                    sid,
                    s.get("quote"),
                    s.get("weight"),
                ),
            )
            inserted += 1
        conn.commit()
        return inserted


def _serialize_page_row(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row)
    for key in ("id", "wiki_space_id"):
        if r.get(key) is not None:
            r[key] = str(r[key])
    for ts in ("created_at", "updated_at"):
        v = r.get(ts)
        if v is not None and hasattr(v, "isoformat"):
            r[ts] = v.isoformat()
    return r


# ---------------------------------------------------------------------------
# Wiki Generation Job + Mutations
# ---------------------------------------------------------------------------


def insert_wiki_job(
    database_url: str,
    *,
    workspace_id: str,
    wiki_space_id: str,
    kind: str = "generate",
) -> str:
    job_id = str(uuid4())
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO wiki_generation_jobs (
              id, workspace_id, wiki_space_id, kind, status, stats
            )
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s, 'queued', '{}'::jsonb)
            """,
            (job_id, workspace_id, wiki_space_id, kind),
        )
        conn.commit()
    return job_id


def update_wiki_job_status(
    database_url: str,
    *,
    job_id: str,
    status: str,
    stats: dict[str, Any] | None = None,
    failure_reason: str | None = None,
) -> None:
    sets = ["status = %s"]
    params: list[Any] = [status]
    if stats is not None:
        sets.append("stats = %s::jsonb")
        params.append(Json(stats))
    if failure_reason is not None:
        sets.append("failure_reason = %s")
        params.append(failure_reason)
    if status in ("succeeded", "failed", "cancelled"):
        sets.append("ended_at = now()")
    params.append(job_id)
    with psycopg.connect(database_url) as conn:
        conn.execute(
            f"UPDATE wiki_generation_jobs SET {', '.join(sets)} WHERE id = %s::uuid",
            tuple(params),
        )
        conn.commit()


def insert_wiki_mutation(
    database_url: str,
    *,
    wiki_job_id: str,
    wiki_page_id: str,
    mutation_type: str,
    payload: dict[str, Any],
) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO wiki_mutations (
              id, wiki_job_id, wiki_page_id, mutation_type, payload
            )
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb)
            """,
            (str(uuid4()), wiki_job_id, wiki_page_id, mutation_type, Json(payload)),
        )
        conn.commit()


def fetch_wiki_job(
    database_url: str,
    *,
    workspace_id: str,
    job_id: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT id, workspace_id, wiki_space_id, kind, status, stats,
                   failure_reason, started_at, ended_at
            FROM wiki_generation_jobs
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            LIMIT 1
            """,
            (job_id, workspace_id),
        ).fetchone()
    if not row:
        return None
    return _serialize_job_row(dict(row))


def list_wiki_job_mutations(
    database_url: str,
    *,
    wiki_job_id: str,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT id, wiki_job_id, wiki_page_id, mutation_type, payload, created_at
            FROM wiki_mutations
            WHERE wiki_job_id = %s::uuid
            ORDER BY created_at ASC
            """,
            (wiki_job_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for k in ("id", "wiki_job_id", "wiki_page_id"):
            if d.get(k) is not None:
                d[k] = str(d[k])
        if hasattr(d.get("created_at"), "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    return out


def _serialize_job_row(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row)
    for key in ("id", "workspace_id", "wiki_space_id"):
        if r.get(key) is not None:
            r[key] = str(r[key])
    for ts in ("started_at", "ended_at"):
        v = r.get(ts)
        if v is not None and hasattr(v, "isoformat"):
            r[ts] = v.isoformat()
    return r


# ---------------------------------------------------------------------------
# Source-note discovery
# ---------------------------------------------------------------------------


def fetch_notes_for_wiki(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return atomic notes available for wiki generation.

    Workspace-wide wiki fetches all notes for the workspace; agent-scoped wiki
    filters strictly by ``agent_id``.
    """
    params: list[Any] = [workspace_id]
    where = "n.workspace_id = %s::uuid"
    if agent_id is not None:
        where += " AND n.agent_id = %s::uuid"
        params.append(agent_id)
    params.append(limit)
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            f"""
            SELECT n.id, n.workspace_id, n.agent_id, n.title, n.body,
                   n.tags, n.memory_context, n.memory_keywords, n.origin
            FROM atomic_notes n
            WHERE {where}
            ORDER BY n.updated_at DESC
            LIMIT %s
            """,
            tuple(params),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for k in ("id", "workspace_id", "agent_id"):
            if d.get(k) is not None:
                d[k] = str(d[k])
        out.append(d)
    return out
