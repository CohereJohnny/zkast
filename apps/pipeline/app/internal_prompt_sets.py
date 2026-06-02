"""Internal routes for the versioned ontology / prompt-set store.

Prompt sets are immutable per (workspace, name, version). Editing produces a new
version (origin ``manual``); auto-tuning produces a new version (origin ``auto``).
The built-in global ``generic/v1`` baseline is read-only here.

See specs/openspecs/composable-eval-harness.md.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import psycopg
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.ontology import ontology_from_doc, validate_ontology
from app.prompt_sets_repo import (
    fetch_prompt_set_row,
    insert_prompt_set,
    list_prompt_sets,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["internal-prompt-sets"])


class PromptSetFieldIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str | None = None
    optional: bool = False
    default: Any = None


class PromptSetTypeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    title: str | None = None
    fields: list[PromptSetFieldIn] = Field(default_factory=list)


class EdgeMapEntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str
    object: str
    edges: list[str] = Field(default_factory=list)


class CreatePromptSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    entity_types: list[PromptSetTypeIn]
    edge_types: list[PromptSetTypeIn] = Field(default_factory=list)
    edge_type_map: list[EdgeMapEntryIn] = Field(default_factory=list)
    instructions: str = ""
    origin: str = Field(default="manual", pattern="^(manual|auto)$")
    derived_from_version: str | None = None


def _row_to_doc(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "workspace_id": str(row["workspace_id"]) if row.get("workspace_id") else None,
        "name": row["name"],
        "version": row["version"],
        "origin": row["origin"],
        "derived_from_version": row.get("derived_from_version"),
        "is_builtin": row["is_builtin"],
        "entity_types": list(row.get("entity_types") or []),
        "edge_types": list(row.get("edge_types") or []),
        "edge_type_map": list(row.get("edge_type_map") or []),
        "instructions": row.get("instructions") or "",
    }


@router.get("/internal/v1/workspaces/{workspace_id}/prompt-sets")
async def list_prompt_sets_route(workspace_id: uuid.UUID, request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    items = await asyncio.to_thread(
        list_prompt_sets, settings.database_url, workspace_id=str(workspace_id)
    )
    return JSONResponse({"items": items})


@router.get("/internal/v1/workspaces/{workspace_id}/prompt-sets/{name}/{version}")
async def get_prompt_set_route(
    workspace_id: uuid.UUID, name: str, version: str, request: Request
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    row = await asyncio.to_thread(
        fetch_prompt_set_row,
        settings.database_url,
        name=name,
        version=version,
        workspace_id=str(workspace_id),
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"prompt set {name}/{version} not found")
    return JSONResponse(_row_to_doc(row))


@router.post("/internal/v1/workspaces/{workspace_id}/prompt-sets")
async def create_prompt_set_route(
    workspace_id: uuid.UUID, body: CreatePromptSetRequest, request: Request
) -> JSONResponse:
    settings: Settings = request.app.state.settings

    ontology = ontology_from_doc(body.model_dump())
    errors = validate_ontology(ontology)
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    try:
        created = await asyncio.to_thread(
            insert_prompt_set,
            settings.database_url,
            ontology=ontology,
            workspace_id=str(workspace_id),
            origin=body.origin,
            derived_from_version=body.derived_from_version,
            is_builtin=False,
        )
    except psycopg.errors.UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail=(
                f"prompt set {body.name}/{body.version} already exists; "
                "versions are immutable — bump the version to edit"
            ),
        )
    return JSONResponse(created, status_code=201)
