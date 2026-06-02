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
from app.graphiti_factory import resolve_cohere_api_key
from app.ontology import ontology_from_doc, validate_ontology
from app.ontology_autotune import autotune_ontology, sample_corpus_texts
from app.prompt_sets_repo import (
    fetch_prompt_set_row,
    insert_prompt_set,
    list_prompt_sets,
    resolve_ontology,
)
from app.workspace_repo import fetch_pipeline_settings

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


class AutotuneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    # Corpus scope (most specific wins): a single document, else an agent / Slack
    # channel memory space, else the whole workspace.
    agent_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    base_name: str = "generic"
    base_version: str = "v1"
    sample_limit: int = Field(default=40, ge=4, le=200)


@router.post("/internal/v1/workspaces/{workspace_id}/prompt-sets/autotune")
async def autotune_prompt_set_route(
    workspace_id: uuid.UUID, body: AutotuneRequest, request: Request
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)

    api_key = resolve_cohere_api_key(settings, ws)
    if not api_key:
        raise HTTPException(status_code=400, detail="No Cohere API key configured for this workspace")

    base = await asyncio.to_thread(
        resolve_ontology,
        settings.database_url,
        name=body.base_name,
        version=body.base_version,
        workspace_id=ws,
    )

    samples = await asyncio.to_thread(
        sample_corpus_texts,
        settings.database_url,
        workspace_id=ws,
        agent_id=str(body.agent_id) if body.agent_id else None,
        document_id=str(body.document_id) if body.document_id else None,
        limit=body.sample_limit,
    )
    if not samples:
        raise HTTPException(
            status_code=422,
            detail=(
                "No raw-chunk corpus to sample for the selected scope; "
                "ingest documents/conversations first or widen the scope"
            ),
        )

    pipe = await asyncio.to_thread(fetch_pipeline_settings, settings.database_url, ws)
    model = str(pipe.get("large_model") or "command-a-plus-05-2026")

    try:
        ontology = await autotune_ontology(
            api_key=api_key,
            model=model,
            samples=samples,
            base=base,
            name=body.name,
            version=body.version,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ontology_autotune_failed", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail=f"Auto-tune failed: {exc}")

    errors = validate_ontology(ontology)
    if errors:
        raise HTTPException(
            status_code=502,
            detail={"message": "Auto-tuned ontology failed validation", "errors": errors},
        )

    try:
        created = await asyncio.to_thread(
            insert_prompt_set,
            settings.database_url,
            ontology=ontology,
            workspace_id=ws,
            origin="auto",
            derived_from_version=body.base_version,
            is_builtin=False,
        )
    except psycopg.errors.UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail=f"prompt set {body.name}/{body.version} already exists; bump the version",
        )

    scope = (
        f"document:{body.document_id}"
        if body.document_id
        else f"agent:{body.agent_id}"
        if body.agent_id
        else "workspace"
    )
    created["stats"] = {
        "samples": len(samples),
        "scope": scope,
        "entity_types": len(ontology.entity_types),
        "edge_types": len(ontology.edge_types),
        "edge_type_map": len(ontology.edge_type_map),
        "derived_from": f"{body.base_name}/{body.base_version}",
    }
    return JSONResponse(created, status_code=201)
