"""Test helpers for optional Postgres integration coverage."""

from __future__ import annotations

import psycopg


def atomic_notes_table_exists(database_url: str) -> bool:
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'atomic_notes'
            LIMIT 1
            """,
        ).fetchone()
        return row is not None


def graph_snapshots_table_exists(database_url: str) -> bool:
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'graph_snapshots'
            LIMIT 1
            """,
        ).fetchone()
        return row is not None


def ingestion_run_logs_table_exists(database_url: str) -> bool:
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'ingestion_run_logs'
            LIMIT 1
            """,
        ).fetchone()
        return row is not None


def merge_audit_log_table_exists(database_url: str) -> bool:
    with psycopg.connect(database_url) as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'merge_audit_log'
            LIMIT 1
            """,
        ).fetchone()
        return row is not None
