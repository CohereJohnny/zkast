"""Workspace baseline reset — wipe derived memory, sources, jobs, and indexes.

Preserves the workspace row, memberships, and (by default) API keys and
pipeline_settings so operators can rebuild from a clean slate for E2E testing.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row

from app.documents_repo import fail_running_ingestion_runs_for_document
from app.job_redis import JOB_HASH_PREFIX, job_stream_key

logger = structlog.get_logger(__name__)

ACTIVE_DOCUMENT_STATUSES = (
    "queued",
    "parsing",
    "generating_notes",
    "extracting_graph",
    "building_graph",
)

ACTIVE_DREAM_STATUSES = ("queued", "running")
ACTIVE_WIKI_JOB_STATUSES = ("queued", "running")


@dataclass
class ResetPreview:
    workspace_id: str
    busy: bool
    busy_reasons: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "busy": self.busy,
            "busy_reasons": self.busy_reasons,
            "counts": self.counts,
        }


@dataclass
class ResetResult:
    workspace_id: str
    postgres: dict[str, int]
    redis_jobs_deleted: int = 0
    graphiti_deleted: bool = False
    storage_cleared: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "postgres": self.postgres,
            "redis_jobs_deleted": self.redis_jobs_deleted,
            "graphiti_deleted": self.graphiti_deleted,
            "storage_cleared": self.storage_cleared,
        }


def _count(conn: psycopg.Connection, sql: str, workspace_id: str) -> int:
    row = conn.execute(sql, (workspace_id,)).fetchone()
    return int(row[0]) if row else 0


def preview_workspace_reset(database_url: str, *, workspace_id: str) -> ResetPreview:
    """Return row counts and whether a reset should be blocked."""
    ws = workspace_id
    counts: dict[str, int] = {}
    busy_reasons: list[str] = []

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        counts["documents"] = _count(
            conn, "SELECT COUNT(*) FROM documents WHERE workspace_id = %s::uuid", ws
        )
        counts["atomic_notes"] = _count(
            conn, "SELECT COUNT(*) FROM atomic_notes WHERE workspace_id = %s::uuid", ws
        )
        counts["entities"] = _count(
            conn, "SELECT COUNT(*) FROM entities WHERE workspace_id = %s::uuid", ws
        )
        counts["relationships"] = _count(
            conn, "SELECT COUNT(*) FROM relationships WHERE workspace_id = %s::uuid", ws
        )
        counts["episodes"] = _count(
            conn, "SELECT COUNT(*) FROM episodes WHERE workspace_id = %s::uuid", ws
        )
        counts["chat_sessions"] = _count(
            conn, "SELECT COUNT(*) FROM chat_sessions WHERE workspace_id = %s::uuid", ws
        )
        counts["retrieval_embeddings"] = _count(
            conn,
            "SELECT COUNT(*) FROM retrieval_embeddings WHERE workspace_id = %s::uuid",
            ws,
        )
        counts["north_agents"] = _count(
            conn, "SELECT COUNT(*) FROM north_agents WHERE workspace_id = %s::uuid", ws
        )
        counts["dream_jobs"] = _count(
            conn, "SELECT COUNT(*) FROM dream_jobs WHERE workspace_id = %s::uuid", ws
        )
        counts["wiki_spaces"] = _count(
            conn, "SELECT COUNT(*) FROM wiki_spaces WHERE workspace_id = %s::uuid", ws
        )
        counts["graph_snapshots"] = _count(
            conn, "SELECT COUNT(*) FROM graph_snapshots WHERE workspace_id = %s::uuid", ws
        )
        counts["chat_eval_runs"] = _count(
            conn, "SELECT COUNT(*) FROM chat_eval_runs WHERE workspace_id = %s::uuid", ws
        )

        active_docs = conn.execute(
            """
            SELECT COUNT(*) AS n FROM documents
            WHERE workspace_id = %s::uuid AND status = ANY(%s)
            """,
            (ws, list(ACTIVE_DOCUMENT_STATUSES)),
        ).fetchone()
        if active_docs and int(active_docs["n"]) > 0:
            busy_reasons.append(f"{active_docs['n']} document(s) mid-ingestion")

        running_ingestion = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM ingestion_runs ir
            JOIN documents d ON d.id = ir.document_id
            WHERE d.workspace_id = %s::uuid AND ir.status = 'running'
            """,
            (ws,),
        ).fetchone()
        if running_ingestion and int(running_ingestion["n"]) > 0:
            busy_reasons.append(f"{running_ingestion['n']} ingestion run(s) still running")

        active_dream = conn.execute(
            """
            SELECT COUNT(*) AS n FROM dream_jobs
            WHERE workspace_id = %s::uuid AND status = ANY(%s)
            """,
            (ws, list(ACTIVE_DREAM_STATUSES)),
        ).fetchone()
        if active_dream and int(active_dream["n"]) > 0:
            busy_reasons.append(f"{active_dream['n']} dream job(s) active")

        active_wiki = conn.execute(
            """
            SELECT COUNT(*) AS n FROM wiki_generation_jobs
            WHERE workspace_id = %s::uuid AND status = ANY(%s)
            """,
            (ws, list(ACTIVE_WIKI_JOB_STATUSES)),
        ).fetchone()
        if active_wiki and int(active_wiki["n"]) > 0:
            busy_reasons.append(f"{active_wiki['n']} wiki job(s) active")

    return ResetPreview(
        workspace_id=ws,
        busy=len(busy_reasons) > 0,
        busy_reasons=busy_reasons,
        counts=counts,
    )


def _cancel_active_work(conn: psycopg.Connection, *, workspace_id: str) -> None:
    """Mark in-flight pipeline rows terminal so workers stop writing."""
    ws = workspace_id
    conn.execute(
        """
        UPDATE ingestion_runs ir
        SET status = 'cancelled', ended_at = now()
        FROM documents d
        WHERE ir.document_id = d.id
          AND d.workspace_id = %s::uuid
          AND ir.status = 'running'
        """,
        (ws,),
    )
    conn.execute(
        """
        UPDATE documents
        SET status = 'failed', failure_reason = 'cancelled_by_workspace_reset'
        WHERE workspace_id = %s::uuid
          AND status = ANY(%s)
        """,
        (ws, list(ACTIVE_DOCUMENT_STATUSES)),
    )
    conn.execute(
        """
        UPDATE dream_jobs
        SET status = 'cancelled', ended_at = now(),
            failure_reason = 'cancelled_by_workspace_reset'
        WHERE workspace_id = %s::uuid AND status = ANY(%s)
        """,
        (ws, list(ACTIVE_DREAM_STATUSES)),
    )
    conn.execute(
        """
        UPDATE wiki_generation_jobs
        SET status = 'cancelled', ended_at = now(),
            failure_reason = 'cancelled_by_workspace_reset'
        WHERE workspace_id = %s::uuid AND status = ANY(%s)
        """,
        (ws, list(ACTIVE_WIKI_JOB_STATUSES)),
    )
    conn.execute(
        """
        UPDATE wiki_spaces
        SET status = 'empty', last_generated_at = NULL
        WHERE workspace_id = %s::uuid AND status = 'generating'
        """,
        (ws,),
    )


def _delete_workspace_content(conn: psycopg.Connection, *, workspace_id: str) -> dict[str, int]:
    """Hard-delete all workspace content; keep workspace + api_keys."""
    ws = workspace_id
    deleted: dict[str, int] = {}

    def _run(label: str, sql: str) -> None:
        cur = conn.execute(sql, (ws,))
        deleted[label] = int(cur.rowcount or 0)

    # Evals (runs cascade questions + results)
    _run("chat_eval_runs", "DELETE FROM chat_eval_runs WHERE workspace_id = %s::uuid")

    # Chat + retrieval debug (sessions cascade messages/citations)
    _run("chat_sessions", "DELETE FROM chat_sessions WHERE workspace_id = %s::uuid")
    _run("retrieval_records", "DELETE FROM retrieval_records WHERE workspace_id = %s::uuid")
    _run(
        "retrieval_embeddings",
        "DELETE FROM retrieval_embeddings WHERE workspace_id = %s::uuid",
    )

    # Wiki (spaces cascade pages, jobs, mutations, links)
    _run("wiki_spaces", "DELETE FROM wiki_spaces WHERE workspace_id = %s::uuid")

    # Dream + North
    _run("dream_jobs", "DELETE FROM dream_jobs WHERE workspace_id = %s::uuid")
    _run(
        "north_conversation_cache",
        "DELETE FROM north_conversation_cache WHERE workspace_id = %s::uuid",
    )
    _run("north_agents", "DELETE FROM north_agents WHERE workspace_id = %s::uuid")

    # Snapshots + merge audit
    _run("graph_snapshots", "DELETE FROM graph_snapshots WHERE workspace_id = %s::uuid")
    _run("merge_audit_log", "DELETE FROM merge_audit_log WHERE workspace_id = %s::uuid")

    # Graph working store (junction tables cascade from notes/entities/rels)
    _run("note_links", "DELETE FROM note_links WHERE workspace_id = %s::uuid")
    _run("atomic_notes", "DELETE FROM atomic_notes WHERE workspace_id = %s::uuid")
    _run("relationships", "DELETE FROM relationships WHERE workspace_id = %s::uuid")
    _run("entities", "DELETE FROM entities WHERE workspace_id = %s::uuid")
    _run("entity_evidence", "DELETE FROM entity_evidence WHERE workspace_id = %s::uuid")

    # Sources (episodes + ingestion runs cascade from documents)
    _run("documents", "DELETE FROM documents WHERE workspace_id = %s::uuid")
    _run(
        "upload_idempotency",
        "DELETE FROM upload_idempotency WHERE workspace_id = %s::uuid",
    )

    return deleted


def reset_workspace_postgres(
    database_url: str,
    *,
    workspace_id: str,
    force: bool = False,
) -> tuple[dict[str, int], ResetPreview]:
    """Cancel active work (when forced) and delete all workspace content rows."""
    preview = preview_workspace_reset(database_url, workspace_id=workspace_id)
    if preview.busy and not force:
        raise WorkspaceResetBusyError(preview.busy_reasons)

    with psycopg.connect(database_url) as conn:
        if force:
            doc_rows = conn.execute(
                """
                SELECT id::text FROM documents WHERE workspace_id = %s::uuid
                """,
                (workspace_id,),
            ).fetchall()
            for row in doc_rows:
                fail_running_ingestion_runs_for_document(
                    database_url, document_id=str(row[0])
                )
            _cancel_active_work(conn, workspace_id=workspace_id)
        deleted = _delete_workspace_content(conn, workspace_id=workspace_id)
        conn.commit()

    return deleted, preview


class WorkspaceResetBusyError(Exception):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


async def purge_workspace_redis_jobs(redis: Any, *, workspace_id: str) -> int:
    """Delete ``zkast:job:*`` hashes and log streams for one workspace."""
    removed = 0
    cursor = 0
    scanned = 0
    max_scan = 5000
    while True:
        cursor, keys = await redis.scan(
            cursor=cursor, match=f"{JOB_HASH_PREFIX}*", count=200
        )
        for key in keys:
            if isinstance(key, bytes):
                key = key.decode()
            scanned += 1
            if scanned > max_scan:
                break
            raw = await redis.hgetall(key)
            if not raw:
                continue
            if isinstance(raw, dict) and any(isinstance(v, bytes) for v in raw.values()):
                raw = {
                    str(kk): (vv.decode() if isinstance(vv, bytes) else vv)
                    for kk, vv in raw.items()
                }
            if raw.get("workspace_id") != workspace_id:
                continue
            job_id = key.removeprefix(JOB_HASH_PREFIX)
            await redis.delete(key, job_stream_key(job_id))
            removed += 1
        if cursor == 0 or scanned > max_scan:
            break
    return removed


async def purge_workspace_graphiti(
    *,
    falkordb_host: str,
    falkordb_port: int,
    workspace_id: str,
) -> bool:
    """Drop the FalkorDB graph named after the workspace UUID."""
    import redis.asyncio as aioredis

    client = aioredis.Redis(host=falkordb_host, port=falkordb_port, decode_responses=True)
    try:
        # FalkorDB: GRAPH.DELETE <graph_name> — idempotent when graph missing.
        await client.execute_command("GRAPH.DELETE", workspace_id)
        logger.info("workspace_reset_graphiti_deleted", workspace_id=workspace_id)
        return True
    except Exception as exc:  # noqa: BLE001
        err = str(exc).lower()
        if "empty" in err or "not exist" in err or "unknown graph" in err:
            return False
        logger.warning(
            "workspace_reset_graphiti_failed",
            workspace_id=workspace_id,
            error=str(exc),
        )
        raise
    finally:
        await client.aclose()


def purge_workspace_storage(storage_root: str, *, workspace_id: str) -> bool:
    """Remove all uploaded files for the workspace and recreate an empty dir."""
    root = Path(storage_root) / workspace_id
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    return True
