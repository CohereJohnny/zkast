"""Persistence for Slack connection, channel sources, and conversation cache.

Slack channels are registered as provider-neutral memory sources in the
generalized registry (physically still ``north_agents`` with
``provider='slack'`` — see specs/openspecs/slack-source.md). Channel
registration therefore reuses ``north_repo.upsert_north_agent``; this module
owns the Slack-specific connection record, the encrypted OAuth token, and the
thread payload cache.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

SLACK_OAUTH_KEY_KIND = "slack_oauth"


# --------------------------------------------------------------------------- #
# OAuth token (encrypted in api_keys, kind='slack_oauth', one per workspace)
# --------------------------------------------------------------------------- #
def store_slack_oauth_token(
    database_url: str,
    *,
    workspace_id: str,
    encrypted_secret: str,
    label: str = "Slack OAuth token",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Upsert the encrypted Slack OAuth token for a workspace.

    The partial unique index ``uq_api_keys_workspace_slack_oauth`` guarantees
    at most one row per workspace, so we delete-then-insert to keep it simple
    and side-effect free for rotation.
    """
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "DELETE FROM api_keys WHERE workspace_id = %s AND kind = %s",
            (workspace_id, SLACK_OAUTH_KEY_KIND),
        )
        conn.execute(
            """
            INSERT INTO api_keys (id, workspace_id, kind, label, encrypted_secret, metadata)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s::jsonb)
            """,
            (
                str(uuid4()),
                workspace_id,
                SLACK_OAUTH_KEY_KIND,
                label[:200],
                encrypted_secret,
                Json(metadata or {}),
            ),
        )
        conn.commit()


def fetch_slack_oauth_secret_row(database_url: str, workspace_id: str) -> str | None:
    """Return encrypted_secret for the workspace's Slack OAuth token, or None."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT encrypted_secret FROM api_keys
            WHERE workspace_id = %s AND kind = %s
            LIMIT 1
            """,
            (workspace_id, SLACK_OAUTH_KEY_KIND),
        ).fetchone()
    return row["encrypted_secret"] if row else None


def delete_slack_oauth_token(database_url: str, workspace_id: str) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "DELETE FROM api_keys WHERE workspace_id = %s AND kind = %s",
            (workspace_id, SLACK_OAUTH_KEY_KIND),
        )
        conn.commit()


# --------------------------------------------------------------------------- #
# Slack connection record (team metadata; token lives in api_keys)
# --------------------------------------------------------------------------- #
def upsert_slack_connection(
    database_url: str,
    *,
    workspace_id: str,
    slack_team_id: str,
    slack_team_name: str | None,
    authed_scopes: list[str],
) -> dict[str, Any]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            INSERT INTO slack_connections (
              workspace_id, slack_team_id, slack_team_name, authed_scopes
            )
            VALUES (%s::uuid, %s, %s, %s)
            ON CONFLICT (workspace_id)
            DO UPDATE SET
              slack_team_id = EXCLUDED.slack_team_id,
              slack_team_name = EXCLUDED.slack_team_name,
              authed_scopes = EXCLUDED.authed_scopes,
              updated_at = now()
            RETURNING *
            """,
            (workspace_id, slack_team_id, slack_team_name, authed_scopes),
        ).fetchone()
        conn.commit()
        assert row
    return _serialize_connection(dict(row))


def fetch_slack_connection(
    database_url: str, *, workspace_id: str
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT * FROM slack_connections WHERE workspace_id = %s::uuid LIMIT 1",
            (workspace_id,),
        ).fetchone()
    return _serialize_connection(dict(row)) if row else None


def delete_slack_connection(database_url: str, *, workspace_id: str) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "DELETE FROM slack_connections WHERE workspace_id = %s::uuid",
            (workspace_id,),
        )
        conn.commit()


def _serialize_connection(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row)
    if r.get("workspace_id") is not None:
        r["workspace_id"] = str(r["workspace_id"])
    for ts in ("installed_at", "updated_at"):
        v = r.get(ts)
        if v is not None and hasattr(v, "isoformat"):
            r[ts] = v.isoformat()
    if not isinstance(r.get("authed_scopes"), list):
        r["authed_scopes"] = list(r.get("authed_scopes") or [])
    return r


# --------------------------------------------------------------------------- #
# Thread payload cache (mirrors north_conversation_cache)
# --------------------------------------------------------------------------- #
def upsert_slack_conversation_cache(
    database_url: str,
    *,
    workspace_id: str,
    source_id: str,
    external_conversation_id: str,
    payload: dict[str, Any],
) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO slack_conversation_cache (
              id, workspace_id, source_id, external_conversation_id, payload, fetched_at
            )
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, now())
            ON CONFLICT (source_id, external_conversation_id)
            DO UPDATE SET
              payload = EXCLUDED.payload,
              fetched_at = now()
            """,
            (str(uuid4()), workspace_id, source_id, external_conversation_id, Json(payload)),
        )
        conn.commit()


def fetch_slack_conversation_cache(
    database_url: str,
    *,
    source_id: str,
    external_conversation_id: str,
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT payload FROM slack_conversation_cache
            WHERE source_id = %s::uuid AND external_conversation_id = %s
            LIMIT 1
            """,
            (source_id, external_conversation_id),
        ).fetchone()
    if not row:
        return None
    return dict(row["payload"]) if isinstance(row["payload"], dict) else {"raw": row["payload"]}


def list_slack_conversation_cache(
    database_url: str,
    *,
    workspace_id: str,
    source_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT external_conversation_id, payload, fetched_at
            FROM slack_conversation_cache
            WHERE workspace_id = %s::uuid AND source_id = %s::uuid
            ORDER BY fetched_at DESC
            LIMIT %s
            """,
            (workspace_id, source_id, limit),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "external_conversation_id": r["external_conversation_id"],
                "payload": dict(r["payload"]) if isinstance(r["payload"], dict) else r["payload"],
                "fetched_at": r["fetched_at"].isoformat() if r["fetched_at"] else None,
            }
        )
    return out
