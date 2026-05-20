"""Test helpers for optional Postgres integration coverage."""

from __future__ import annotations

import os

import psycopg

_PLACEHOLDER_URLS = frozenset(
    {
        "...",
        "postgresql://...",
        "postgres://...",
        "postgresql://user:pass@host:5432/db",
    },
)


def get_database_url() -> str | None:
    """Return ``DATABASE_URL`` when it looks like a real Postgres DSN, else ``None``."""
    raw = (os.environ.get("DATABASE_URL") or "").strip()
    if not raw or raw in _PLACEHOLDER_URLS:
        return None
    if not raw.startswith(("postgresql://", "postgres://")):
        return None
    # Minimal shape: scheme://[userinfo@]host[:port]/dbname
    if "@" not in raw or raw.rstrip("/").count("/") < 3:
        return None
    return raw


def postgres_reachable(database_url: str, *, connect_timeout: int = 3) -> bool:
    try:
        with psycopg.connect(database_url, connect_timeout=connect_timeout) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def atomic_notes_table_exists(database_url: str) -> bool:
    try:
        with psycopg.connect(database_url, connect_timeout=3) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'atomic_notes'
                LIMIT 1
                """,
            ).fetchone()
            return row is not None
    except Exception:
        return False


def graph_snapshots_table_exists(database_url: str) -> bool:
    try:
        with psycopg.connect(database_url, connect_timeout=3) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'graph_snapshots'
                LIMIT 1
                """,
            ).fetchone()
            return row is not None
    except Exception:
        return False


def ingestion_run_logs_table_exists(database_url: str) -> bool:
    try:
        with psycopg.connect(database_url, connect_timeout=3) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'ingestion_run_logs'
                LIMIT 1
                """,
            ).fetchone()
            return row is not None
    except Exception:
        return False


def ensure_test_north_agent(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str,
    display_name: str | None = None,
) -> str:
    """Insert a ``north_agents`` row so ``atomic_notes.agent_id`` FK succeeds (migration 0011)."""
    label = display_name or f"Test agent {agent_id[:8]}"
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO north_agents (
              id, workspace_id, external_agent_id, provider, display_name, import_settings
            )
            VALUES (%s::uuid, %s::uuid, %s, 'north', %s, '{}'::jsonb)
            ON CONFLICT (workspace_id, provider, external_agent_id) DO NOTHING
            """,
            (agent_id, workspace_id, f"test-{agent_id}", label[:500]),
        )
        conn.commit()
    return agent_id


def delete_test_north_agent(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str,
) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "DELETE FROM north_agents WHERE id = %s::uuid AND workspace_id = %s::uuid",
            (agent_id, workspace_id),
        )
        conn.commit()


def merge_audit_log_table_exists(database_url: str) -> bool:
    try:
        with psycopg.connect(database_url, connect_timeout=3) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'merge_audit_log'
                LIMIT 1
                """,
            ).fetchone()
            return row is not None
    except Exception:
        return False
