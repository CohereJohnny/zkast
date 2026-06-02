"""Postgres repo for pipeline_configurations (runtime store of record).

The DB is the store of record; configurations also have a portable YAML form
(apps/pipeline/app/pipeline_configs/*.yaml) used for repo seeds + export.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.pipeline_stages.base import PipelineConfiguration


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row)
    for key in ("id", "workspace_id"):
        if r.get(key) is not None:
            r[key] = str(r[key])
    for ts in ("created_at", "updated_at"):
        v = r.get(ts)
        if v is not None and hasattr(v, "isoformat"):
            r[ts] = v.isoformat()
    if r.get("params") is not None and not isinstance(r["params"], dict):
        r["params"] = dict(r["params"])
    return r


def list_pipeline_configurations(
    database_url: str, *, workspace_id: str | None = None
) -> list[dict[str, Any]]:
    """Global (workspace_id IS NULL) configurations plus the workspace's own."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT * FROM pipeline_configurations
            WHERE workspace_id IS NULL OR workspace_id = %s::uuid
            ORDER BY is_builtin DESC, name ASC, version DESC
            """,
            (workspace_id,),
        ).fetchall()
    return [_serialize(dict(r)) for r in rows]


def fetch_pipeline_configuration(
    database_url: str, *, configuration_id: str
) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT * FROM pipeline_configurations WHERE id = %s::uuid LIMIT 1",
            (configuration_id,),
        ).fetchone()
    return _serialize(dict(row)) if row else None


def fetch_builtin_default(database_url: str) -> dict[str, Any] | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT * FROM pipeline_configurations
            WHERE is_builtin = true AND workspace_id IS NULL
            ORDER BY version DESC
            LIMIT 1
            """,
        ).fetchone()
    return _serialize(dict(row)) if row else None


def insert_pipeline_configuration(
    database_url: str,
    *,
    config: PipelineConfiguration,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    cid = str(uuid4())
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            INSERT INTO pipeline_configurations (
              id, workspace_id, name, description, extractor, ontology_version,
              graph_store, retrieval_strategy, provider, params, version,
              content_hash, is_builtin
            )
            VALUES (
              %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s
            )
            RETURNING *
            """,
            (
                cid,
                workspace_id,
                config.name,
                config.description,
                config.extractor,
                config.ontology_version,
                config.graph_store,
                config.retrieval_strategy,
                config.provider,
                Json(config.params or {}),
                config.version,
                config.content_hash,
                config.is_builtin,
            ),
        ).fetchone()
        conn.commit()
        assert row
    return _serialize(dict(row))
