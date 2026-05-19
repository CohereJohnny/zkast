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
