"""Postgres reads/writes for documents, ingestion runs, episodes (sync psycopg)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from app.north_checksum import text_content_hash
from psycopg.rows import dict_row
from psycopg.types.json import Json


def _uuid_str(row: dict[str, Any], key: str) -> None:
    if row.get(key) is not None:
        row[key] = str(row[key])


def fetch_document_by_checksum(
    database_url: str,
    *,
    workspace_id: str,
    checksum: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM documents
            WHERE workspace_id = %s::uuid AND checksum = %s
            LIMIT 1
            """,
            (workspace_id, checksum),
        ).fetchone()
        if not row:
            return None
        _uuid_str(row, "id")
        _uuid_str(row, "workspace_id")
        if row.get("replaces_document_id"):
            _uuid_str(row, "replaces_document_id")
        return row


def fetch_latest_north_documents_by_conversation(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str,
) -> dict[str, dict[str, Any]]:
    """Latest north_conversation document per ``north_conversation_id`` for an agent."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT ON (north_conversation_id)
              north_conversation_id,
              id,
              checksum,
              status,
              created_at,
              north_metadata
            FROM documents
            WHERE workspace_id = %s::uuid
              AND agent_id = %s::uuid
              AND source_kind = 'north_conversation'
              AND north_conversation_id IS NOT NULL
            ORDER BY north_conversation_id, created_at DESC
            """,
            (workspace_id, agent_id),
        ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        cid = str(row.get("north_conversation_id") or "").strip()
        if not cid:
            continue
        doc = dict(row)
        if doc.get("id") is not None:
            doc["id"] = str(doc["id"])
        meta = doc.get("north_metadata")
        if isinstance(meta, dict):
            doc["north_metadata"] = meta
        elif meta is not None:
            doc["north_metadata"] = dict(meta)
        out[cid] = doc
    return out


def fetch_document(
    database_url: str,
    *,
    workspace_id: str,
    document_id: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT * FROM documents
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            LIMIT 1
            """,
            (document_id, workspace_id),
        ).fetchone()
        if not row:
            return None
        _uuid_str(row, "id")
        _uuid_str(row, "workspace_id")
        if row.get("replaces_document_id"):
            _uuid_str(row, "replaces_document_id")
        if row.get("agent_id"):
            _uuid_str(row, "agent_id")
        if row.get("collection_id"):
            _uuid_str(row, "collection_id")
        return row


def list_documents_for_workspace(
    database_url: str,
    workspace_id: str,
    *,
    limit: int = 200,
    collection_id: str | None = None,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        if collection_id:
            rows = conn.execute(
                """
                SELECT *
                FROM documents
                WHERE workspace_id = %s::uuid AND collection_id = %s::uuid
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (workspace_id, collection_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM documents
                WHERE workspace_id = %s::uuid
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (workspace_id, limit),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            _uuid_str(row, "id")
            _uuid_str(row, "workspace_id")
            if row.get("replaces_document_id"):
                _uuid_str(row, "replaces_document_id")
            if row.get("agent_id"):
                _uuid_str(row, "agent_id")
            if row.get("collection_id"):
                _uuid_str(row, "collection_id")
            out.append(row)
        return out


def list_document_ids_for_agent(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str,
) -> list[str]:
    """Document ids owned by a North agent within a workspace."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT id::text AS id
            FROM documents
            WHERE workspace_id = %s::uuid AND agent_id = %s::uuid
            """,
            (workspace_id, agent_id),
        ).fetchall()
        return [r["id"] for r in rows]


def list_document_ids_for_collection(
    database_url: str,
    *,
    workspace_id: str,
    collection_id: str,
) -> list[str]:
    """Document ids in a named collection within a workspace."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT id::text AS id
            FROM documents
            WHERE workspace_id = %s::uuid AND collection_id = %s::uuid
            """,
            (workspace_id, collection_id),
        ).fetchall()
        return [r["id"] for r in rows]


def list_episodes_for_ingestion_run(
    database_url: str,
    *,
    ingestion_run_id: str,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT id, workspace_id, document_id, ingestion_run_id, kind, text,
                   page_start, page_end, sequence, created_at, agent_id
            FROM episodes
            WHERE ingestion_run_id = %s::uuid
            ORDER BY sequence ASC
            """,
            (ingestion_run_id,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            r = dict(row)
            _uuid_str(r, "id")
            _uuid_str(r, "workspace_id")
            _uuid_str(r, "document_id")
            _uuid_str(r, "ingestion_run_id")
            if r.get("agent_id"):
                _uuid_str(r, "agent_id")
            out.append(r)
        return out


def merge_run_stats_incremental(database_url: str, *, run_id: str, extra: dict[str, Any]) -> None:
    """Merge keys into ingestion_runs.stats without closing the run."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT stats FROM ingestion_runs WHERE id = %s::uuid",
            (run_id,),
        ).fetchone()
        if not row:
            return
        stats = dict(row["stats"] if row["stats"] else {})
        stats.update(extra)
        conn.execute(
            "UPDATE ingestion_runs SET stats = %s::jsonb WHERE id = %s::uuid",
            (Json(stats), run_id),
        )
        conn.commit()


def finalize_ingestion_run_success(
    database_url: str,
    *,
    run_id: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Mark ingestion run succeeded with optional final stats merge."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT stats FROM ingestion_runs WHERE id = %s::uuid",
            (run_id,),
        ).fetchone()
        stats = dict(row["stats"] if row and row["stats"] else {})
        if extra:
            stats.update(extra)
        conn.execute(
            """
            UPDATE ingestion_runs
            SET status = 'succeeded', ended_at = now(), stats = %s::jsonb
            WHERE id = %s::uuid
            """,
            (Json(stats), run_id),
        )
        conn.commit()


def is_document_ingestion_active(database_url: str, *, document_id: str) -> bool:
    """True while a document is mid-pipeline or has a run still marked running."""
    active_statuses = (
        "queued",
        "parsing",
        "generating_notes",
        "extracting_graph",
        "building_graph",
    )
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT status FROM documents WHERE id = %s::uuid LIMIT 1",
            (document_id,),
        ).fetchone()
        if not row:
            return False
        if row["status"] in active_statuses:
            return True
        run = conn.execute(
            """
            SELECT 1 AS ok
            FROM ingestion_runs
            WHERE document_id = %s::uuid AND status = 'running'
            LIMIT 1
            """,
            (document_id,),
        ).fetchone()
        return run is not None


def fail_running_ingestion_runs_for_document(database_url: str, *, document_id: str) -> int:
    """Mark in-flight ingestion runs as cancelled when superseded (retry / new attempt). Not a pipeline error."""
    with psycopg.connect(database_url) as conn:
        cur = conn.execute(
            """
            UPDATE ingestion_runs
            SET status = 'cancelled', ended_at = now()
            WHERE document_id = %s::uuid AND status = 'running'
            """,
            (document_id,),
        )
        n = cur.rowcount
        conn.commit()
    return int(n or 0)


def restart_ingestion_run(database_url: str, *, run_id: str) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            UPDATE ingestion_runs
            SET status = 'running', ended_at = NULL, last_heartbeat_at = now()
            WHERE id = %s::uuid
            """,
            (run_id,),
        )
        conn.commit()


def update_ingestion_run_heartbeat(database_url: str, *, run_id: str) -> None:
    """Bump ``last_heartbeat_at`` so the reconciler treats this run as alive.

    Sprint 5b: tasks call this every 10s via :class:`_Heartbeat`. The column
    is added by migration ``0007_ingestion_observability``.
    """
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE ingestion_runs SET last_heartbeat_at = now() WHERE id = %s::uuid",
            (run_id,),
        )
        conn.commit()


def list_stalled_active_documents(
    database_url: str,
    *,
    stale_seconds: int = 90,
) -> list[dict[str, Any]]:
    """Find documents in an active status whose ingestion-run heartbeat is stale.

    Returns rows ready to flip to ``failed``. Joins to the most recent
    running ``ingestion_runs`` row for each document and filters those whose
    ``last_heartbeat_at`` is older than ``stale_seconds`` (or NULL — older
    runs from before migration 0007 land in this bucket too once their
    document has been active beyond the threshold).
    """
    active_statuses = (
        "queued",
        "parsing",
        "generating_notes",
        "extracting_graph",
        "building_graph",
    )
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
              d.id::text AS document_id,
              d.workspace_id::text AS workspace_id,
              d.status,
              ir.id::text AS ingestion_run_id,
              ir.last_heartbeat_at,
              d.updated_at
            FROM documents d
            LEFT JOIN LATERAL (
              SELECT id, last_heartbeat_at
              FROM ingestion_runs
              WHERE document_id = d.id AND status = 'running'
              ORDER BY started_at DESC
              LIMIT 1
            ) ir ON true
            WHERE d.status = ANY(%s::text[])
              AND (
                ir.last_heartbeat_at IS NULL
                OR ir.last_heartbeat_at < (now() - make_interval(secs => %s))
              )
              AND d.updated_at < (now() - make_interval(secs => %s))
            """,
            (list(active_statuses), stale_seconds, stale_seconds),
        ).fetchall()
        return [dict(r) for r in rows]


def resolve_document_run_for_episodes(
    database_url: str,
    *,
    workspace_id: str,
    episode_ids: list[str],
) -> tuple[str, str] | None:
    """If all episodes exist in workspace and share one document + ingestion run, return (document_id, run_id)."""
    if not episode_ids:
        return None
    uniq = list(dict.fromkeys(episode_ids))
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT document_id::text AS document_id, ingestion_run_id::text AS ingestion_run_id
            FROM episodes
            WHERE workspace_id = %s::uuid AND id = ANY(%s::uuid[])
            """,
            (workspace_id, uniq),
        ).fetchall()
        if len(rows) != len(uniq):
            return None
        doc_ids = {r["document_id"] for r in rows}
        run_ids = {r["ingestion_run_id"] for r in rows}
        if len(doc_ids) != 1 or len(run_ids) != 1:
            return None
        return (doc_ids.pop(), run_ids.pop())


def fetch_latest_ingestion_run_with_episodes(database_url: str, *, document_id: str) -> str | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT ir.id::text AS id
            FROM ingestion_runs ir
            WHERE ir.document_id = %s::uuid
              AND EXISTS (SELECT 1 FROM episodes e WHERE e.ingestion_run_id = ir.id)
            ORDER BY ir.started_at DESC
            LIMIT 1
            """,
            (document_id,),
        ).fetchone()
        return str(row["id"]) if row else None


def list_ingestion_runs_for_document(
    database_url: str,
    *,
    document_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM ingestion_runs
            WHERE document_id = %s::uuid
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (document_id, limit),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            _uuid_str(row, "id")
            _uuid_str(row, "document_id")
            out.append(row)
        return out


def insert_document(
    database_url: str,
    *,
    document_id: str,
    workspace_id: str,
    original_filename: str,
    mime_type: str,
    byte_size: int,
    storage_uri: str,
    checksum: str,
    replaces_document_id: str | None,
    status: str,
    source_kind: str = "pdf",
    agent_id: str | None = None,
    collection_id: str | None = None,
    north_conversation_id: str | None = None,
    north_metadata: dict[str, Any] | None = None,
    raw_transcript_json: dict[str, Any] | list[Any] | None = None,
    external_conversation_id: str | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            INSERT INTO documents (
              id, workspace_id, original_filename, mime_type, byte_size,
              storage_uri, checksum, replaces_document_id, status,
              source_kind, agent_id, collection_id, north_conversation_id, north_metadata,
              raw_transcript_json, external_conversation_id, source_metadata
            )
            VALUES (
              %s::uuid, %s::uuid, %s, %s, %s, %s, %s,
              %s::uuid, %s, %s, %s::uuid, %s::uuid, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb
            )
            RETURNING *
            """,
            (
                document_id,
                workspace_id,
                original_filename,
                mime_type,
                byte_size,
                storage_uri,
                checksum,
                replaces_document_id,
                status,
                source_kind,
                agent_id,
                collection_id,
                north_conversation_id,
                Json(north_metadata or {}),
                Json(raw_transcript_json) if raw_transcript_json is not None else None,
                external_conversation_id,
                Json(source_metadata or {}),
            ),
        ).fetchone()
        conn.commit()
        assert row
        _uuid_str(row, "id")
        _uuid_str(row, "workspace_id")
        if row.get("replaces_document_id"):
            _uuid_str(row, "replaces_document_id")
        if row.get("agent_id"):
            _uuid_str(row, "agent_id")
        if row.get("collection_id"):
            _uuid_str(row, "collection_id")
        return row


def insert_ingestion_run(
    database_url: str,
    *,
    run_id: str,
    document_id: str,
    status: str,
    pipeline_version: str,
    llm_provider: str,
    llm_model_small: str,
    llm_model_large: str,
    stats: dict[str, Any] | None = None,
    trace_id: str | None = None,
    ontology_name: str = "generic",
    ontology_version: str = "v1",
) -> dict[str, Any]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            INSERT INTO ingestion_runs (
              id, document_id, status, pipeline_version,
              llm_provider, llm_model_small, llm_model_large, stats, trace_id,
              ontology_name, ontology_version
            )
            VALUES (
              %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s
            )
            RETURNING *
            """,
            (
                run_id,
                document_id,
                status,
                pipeline_version,
                llm_provider,
                llm_model_small,
                llm_model_large,
                Json(stats or {}),
                trace_id,
                ontology_name,
                ontology_version,
            ),
        ).fetchone()
        conn.commit()
        assert row
        _uuid_str(row, "id")
        _uuid_str(row, "document_id")
        return row


def fetch_ingestion_run_ontology(
    database_url: str, *, ingestion_run_id: str
) -> tuple[str, str]:
    """Return ``(ontology_name, ontology_version)`` for a run; defaults to generic/v1."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT ontology_name, ontology_version
            FROM ingestion_runs
            WHERE id = %s::uuid
            """,
            (ingestion_run_id,),
        ).fetchone()
    if not row:
        return ("generic", "v1")
    name = (row.get("ontology_name") or "generic").strip() or "generic"
    version = (row.get("ontology_version") or "v1").strip() or "v1"
    return (name, version)


def fetch_latest_document_ontology(
    database_url: str, *, document_id: str
) -> tuple[str, str]:
    """Most recent ontology selection for a document; defaults to generic/v1."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT ontology_name, ontology_version
            FROM ingestion_runs
            WHERE document_id = %s::uuid
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (document_id,),
        ).fetchone()
    if not row:
        return ("generic", "v1")
    name = (row.get("ontology_name") or "generic").strip() or "generic"
    version = (row.get("ontology_version") or "v1").strip() or "v1"
    return (name, version)


def update_document(
    database_url: str,
    *,
    document_id: str,
    status: str | None = None,
    page_count: int | None = None,
    failure_reason: str | None = None,
    byte_size: int | None = None,
    clear_failure_reason: bool = False,
) -> None:
    sets: list[str] = ["updated_at = now()"]
    params: list[Any] = []
    if status is not None:
        sets.append("status = %s")
        params.append(status)
    if page_count is not None:
        sets.append("page_count = %s")
        params.append(page_count)
    if clear_failure_reason:
        sets.append("failure_reason = NULL")
    elif failure_reason is not None:
        sets.append("failure_reason = %s")
        params.append(failure_reason)
    if byte_size is not None:
        sets.append("byte_size = %s")
        params.append(byte_size)
    params.append(document_id)
    q = f"UPDATE documents SET {', '.join(sets)} WHERE id = %s::uuid"
    with psycopg.connect(database_url) as conn:
        conn.execute(q, params)
        conn.commit()


def update_ingestion_run(
    database_url: str,
    *,
    run_id: str,
    status: str | None = None,
    ended_at: datetime | None = None,
    stats: dict[str, Any] | None = None,
) -> None:
    sets: list[str] = []
    params: list[Any] = []
    if status is not None:
        sets.append("status = %s")
        params.append(status)
    if ended_at is not None:
        sets.append("ended_at = %s")
        params.append(ended_at)
    if stats is not None:
        sets.append("stats = %s::jsonb")
        params.append(Json(stats))
    if not sets:
        return
    params.append(run_id)
    q = f"UPDATE ingestion_runs SET {', '.join(sets)} WHERE id = %s::uuid"
    with psycopg.connect(database_url) as conn:
        conn.execute(q, params)
        conn.commit()


def merge_run_stats_warning(database_url: str, *, run_id: str, warning: str) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT stats FROM ingestion_runs WHERE id = %s::uuid",
            (run_id,),
        ).fetchone()
        if not row:
            return
        stats = dict(row["stats"] or {})
        warnings = list(stats.get("warnings") or [])
        warnings.append(warning)
        stats["warnings"] = warnings
        conn.execute(
            "UPDATE ingestion_runs SET stats = %s::jsonb WHERE id = %s::uuid",
            (Json(stats), run_id),
        )
        conn.commit()


def delete_episodes_for_document(database_url: str, *, document_id: str) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute("DELETE FROM episodes WHERE document_id = %s::uuid", (document_id,))
        conn.commit()


def insert_episodes(
    database_url: str,
    *,
    workspace_id: str,
    document_id: str,
    ingestion_run_id: str,
    rows: list[tuple[str, str, int, int, int, str, str | None]],
) -> None:
    """rows: (episode_id, text, page_start, page_end, sequence, kind, agent_id)"""
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO episodes (
                  id, workspace_id, document_id, ingestion_run_id,
                  kind, text, page_start, page_end, sequence, agent_id,
                  source_content_hash
                )
                VALUES (
                  %s::uuid, %s::uuid, %s::uuid, %s::uuid,
                  %s, %s, %s, %s, %s, %s::uuid, %s
                )
                """,
                [
                    (
                        r[0],
                        workspace_id,
                        document_id,
                        ingestion_run_id,
                        r[5],
                        r[1],
                        r[2],
                        r[3],
                        r[4],
                        r[6],
                        text_content_hash(str(r[1])),
                    )
                    for r in rows
                ],
            )
        conn.commit()


def fetch_idempotency(
    database_url: str,
    *,
    key: str,
    workspace_id: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT document_id, job_id
            FROM upload_idempotency
            WHERE key = %s AND workspace_id = %s::uuid
              AND created_at > now() - interval '24 hours'
            LIMIT 1
            """,
            (key, workspace_id),
        ).fetchone()
        if not row:
            return None
        return {"document_id": str(row["document_id"]), "job_id": row["job_id"]}


def cleanup_expired_idempotency(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "DELETE FROM upload_idempotency WHERE created_at < now() - interval '24 hours'",
        )
        conn.commit()


def insert_idempotency(
    database_url: str,
    *,
    key: str,
    workspace_id: str,
    document_id: str,
    job_id: str,
) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO upload_idempotency (key, workspace_id, document_id, job_id)
            VALUES (%s, %s::uuid, %s::uuid, %s)
            """,
            (key, workspace_id, document_id, job_id),
        )
        conn.commit()


def fetch_workspace_id_for_document(database_url: str, document_id: str) -> str | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT workspace_id::text AS workspace_id FROM documents WHERE id = %s::uuid LIMIT 1",
            (document_id,),
        ).fetchone()
        return str(row["workspace_id"]) if row else None


def merge_run_completion_stats(
    database_url: str,
    *,
    run_id: str,
    extra: dict[str, Any],
    status: str,
) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT stats FROM ingestion_runs WHERE id = %s::uuid",
            (run_id,),
        ).fetchone()
        stats = dict(row["stats"] if row and row["stats"] else {})
        stats.update(extra)
        conn.execute(
            """
            UPDATE ingestion_runs
            SET status = %s, ended_at = now(), stats = %s::jsonb
            WHERE id = %s::uuid
            """,
            (status, Json(stats), run_id),
        )
        conn.commit()


def delete_document_row(database_url: str, *, workspace_id: str, document_id: str) -> dict[str, Any] | None:
    """Returns deleted row (including storage_uri) or None."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            DELETE FROM documents
            WHERE id = %s::uuid AND workspace_id = %s::uuid
            RETURNING *
            """,
            (document_id, workspace_id),
        ).fetchone()
        conn.commit()
        return row

