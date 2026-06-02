"""Postgres repo for prompt_sets (versioned ontology store of record).

The built-in ``generic/v1`` baseline is seeded from the config-as-code YAML
(app/ontologies/generic_v1.yaml). resolve_ontology get-or-seeds so the runtime
always has the baseline available without a separate seed step.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.ontology import Ontology, load_ontology_file, ontology_from_doc

BUILTIN_NAME = "generic"
BUILTIN_VERSION = "v1"


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row)
    for key in ("id", "workspace_id"):
        if r.get(key) is not None:
            r[key] = str(r[key])
    if r.get("created_at") is not None and hasattr(r["created_at"], "isoformat"):
        r["created_at"] = r["created_at"].isoformat()
    return r


def _row_to_ontology(row: dict[str, Any]) -> Ontology:
    return ontology_from_doc(
        {
            "name": row["name"],
            "version": row["version"],
            "entity_types": list(row.get("entity_types") or []),
            "edge_types": list(row.get("edge_types") or []),
            "edge_type_map": list(row.get("edge_type_map") or []),
            "instructions": row.get("instructions") or "",
        }
    )


def list_prompt_sets(database_url: str, *, workspace_id: str | None = None) -> list[dict[str, Any]]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT id, workspace_id, name, version, origin, derived_from_version,
                   is_builtin, created_at
            FROM prompt_sets
            WHERE workspace_id IS NULL OR workspace_id = %s::uuid
            ORDER BY is_builtin DESC, name ASC, version DESC
            """,
            (workspace_id,),
        ).fetchall()
    return [_serialize(dict(r)) for r in rows]


def fetch_prompt_set_row(
    database_url: str, *, name: str, version: str, workspace_id: str | None = None
) -> dict[str, Any] | None:
    """Prefer a workspace-scoped row, fall back to the global one."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            SELECT * FROM prompt_sets
            WHERE name = %s AND version = %s
              AND (workspace_id = %s::uuid OR workspace_id IS NULL)
            ORDER BY (workspace_id IS NOT NULL) DESC
            LIMIT 1
            """,
            (name, version, workspace_id),
        ).fetchone()
    return dict(row) if row else None


def insert_prompt_set(
    database_url: str,
    *,
    ontology: Ontology,
    workspace_id: str | None = None,
    origin: str = "manual",
    derived_from_version: str | None = None,
    is_builtin: bool = False,
) -> dict[str, Any]:
    doc = ontology.to_doc()
    pid = str(uuid4())
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute(
            """
            INSERT INTO prompt_sets (
              id, workspace_id, name, version, origin, derived_from_version,
              entity_types, edge_types, edge_type_map, instructions, is_builtin
            )
            VALUES (
              %s::uuid, %s::uuid, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s
            )
            RETURNING id, workspace_id, name, version, origin, derived_from_version,
                      is_builtin, created_at
            """,
            (
                pid,
                workspace_id,
                ontology.name,
                ontology.version,
                origin,
                derived_from_version,
                Json(doc["entity_types"]),
                Json(doc["edge_types"]),
                Json(doc["edge_type_map"]),
                ontology.instructions,
                is_builtin,
            ),
        ).fetchone()
        conn.commit()
        assert row
    return _serialize(dict(row))


def ensure_builtin_seeded(database_url: str) -> None:
    """Idempotently seed the global generic/v1 baseline from the YAML."""
    if fetch_prompt_set_row(database_url, name=BUILTIN_NAME, version=BUILTIN_VERSION) is not None:
        return
    ontology = load_ontology_file(BUILTIN_NAME, BUILTIN_VERSION)
    insert_prompt_set(
        database_url,
        ontology=ontology,
        workspace_id=None,
        origin="generic",
        is_builtin=True,
    )


def resolve_ontology(
    database_url: str,
    *,
    name: str = BUILTIN_NAME,
    version: str = BUILTIN_VERSION,
    workspace_id: str | None = None,
) -> Ontology:
    """Load an ontology from the store, get-or-seeding the builtin baseline.

    Falls back to the config-as-code YAML if the requested set is the builtin
    baseline and the DB is unavailable/unseeded.
    """
    row = fetch_prompt_set_row(database_url, name=name, version=version, workspace_id=workspace_id)
    if row is None and (name, version) == (BUILTIN_NAME, BUILTIN_VERSION):
        ensure_builtin_seeded(database_url)
        row = fetch_prompt_set_row(database_url, name=name, version=version, workspace_id=workspace_id)
    if row is None:
        raise LookupError(f"prompt set {name}/{version} not found")
    return _row_to_ontology(row)
