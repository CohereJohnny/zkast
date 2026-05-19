"""Postgres reads/writes for workspaces and api_keys (sync psycopg)."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row


DEFAULT_PIPELINE_SETTINGS: dict[str, Any] = {
    "chunk_size": 512,
    "max_notes_per_document": 500,
    "language": "en",
    "default_llm_provider": "cohere",
    "small_model": "command-r7b-12-2024",
    "large_model": "command-a-plus-05-2026",
    "embed_model": "embed-v4.0",
    "rerank_model": "rerank-v4.0-fast",
    "include_provenance_subgraph_default": True,
    # North Agents API base URL (optional). Bearer token is stored in
    # ``api_keys`` row kind ``north_bearer`` (encrypted), not in JSON.
    "north_base_url": None,
    # Offline dreaming caps (per agent run).
    "dreaming_max_notes": 60,
    "dreaming_neighbors_per_note": 6,
    "dreaming_pairs_per_run": 360,
}


def merge_pipeline_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    return {**DEFAULT_PIPELINE_SETTINGS, **(raw or {})}


def fetch_pipeline_settings(database_url: str, workspace_id: str) -> dict[str, Any]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT pipeline_settings FROM workspaces WHERE id = %s",
            (workspace_id,),
        ).fetchone()
        if not row:
            raise ValueError("workspace not found")
        return merge_pipeline_settings(row["pipeline_settings"])


def fetch_llm_cohere_secret_row(database_url: str, workspace_id: str) -> str | None:
    """Return encrypted_secret payload for llm_cohere or None."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT encrypted_secret FROM api_keys
            WHERE workspace_id = %s AND kind = 'llm_cohere'
            LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
        return row["encrypted_secret"] if row else None


def touch_llm_cohere_last_used(database_url: str, workspace_id: str) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            UPDATE api_keys SET last_used_at = now(), updated_at = now()
            WHERE workspace_id = %s AND kind = 'llm_cohere'
            """,
            (workspace_id,),
        )
        conn.commit()


def fetch_north_bearer_secret_row(database_url: str, workspace_id: str) -> str | None:
    """Return encrypted_secret for ``north_bearer`` or None."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT encrypted_secret FROM api_keys
            WHERE workspace_id = %s AND kind = 'north_bearer'
            LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
        return row["encrypted_secret"] if row else None


def touch_north_bearer_last_used(database_url: str, workspace_id: str) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            UPDATE api_keys SET last_used_at = now(), updated_at = now()
            WHERE workspace_id = %s AND kind = 'north_bearer'
            """,
            (workspace_id,),
        )
        conn.commit()
