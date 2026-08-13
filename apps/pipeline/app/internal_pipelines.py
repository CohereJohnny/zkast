"""Internal routes for Pipeline Configurations (the composable-harness Lab).

Lists named stage compositions, exposes the registry's available stage plugins +
ontology versions + providers (so the editor can populate selectors), and
creates new versioned, content-hashed configurations.
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
from app.pipeline_configurations_repo import (
    insert_pipeline_configuration,
    list_pipeline_configurations,
)
from app.pipeline_stages.base import PipelineConfiguration
from app.pipeline_stages.registry import EXTRACTORS, GRAPH_STORES, RETRIEVERS
from app.prompt_sets_repo import list_prompt_sets
from app.providers import KNOWN_PROVIDERS

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["internal-pipelines"])


def _plugins(d: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"id": p.id, "label": p.label, "description": p.description, "implemented": p.implemented}
        for p in d.values()
    ]


class CreateConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    extractor: str
    graph_store: str
    retrieval_strategy: str
    ontology_version: str | None = None
    provider: str = "cohere_compat"
    params: dict[str, Any] = Field(default_factory=dict)


@router.get("/internal/v1/workspaces/{workspace_id}/pipeline-configurations")
async def list_configs_route(workspace_id: uuid.UUID, request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    items = await asyncio.to_thread(
        list_pipeline_configurations, settings.database_url, workspace_id=str(workspace_id)
    )
    return JSONResponse({"items": items})


@router.get("/internal/v1/workspaces/{workspace_id}/pipeline-stages")
async def list_stages_route(workspace_id: uuid.UUID, request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    prompt_sets = await asyncio.to_thread(
        list_prompt_sets, settings.database_url, workspace_id=str(workspace_id)
    )
    ontology_versions = [
        {
            "id": f"{p['name']}_{p['version']}",
            "label": f"{p['name']}/{p['version']} ({p['origin']})",
            "name": p["name"],
            "version": p["version"],
        }
        for p in prompt_sets
    ]
    return JSONResponse(
        {
            "extractors": _plugins(EXTRACTORS),
            "graph_stores": _plugins(GRAPH_STORES),
            "retrievers": _plugins(RETRIEVERS),
            "providers": [{"id": s.id, "label": s.label} for s in KNOWN_PROVIDERS.values()],
            "ontology_versions": ontology_versions,
        }
    )


@router.post("/internal/v1/workspaces/{workspace_id}/pipeline-configurations")
async def create_config_route(
    workspace_id: uuid.UUID, body: CreateConfigRequest, request: Request
) -> JSONResponse:
    settings: Settings = request.app.state.settings

    errors = []
    if body.extractor not in EXTRACTORS:
        errors.append(f"unknown extractor {body.extractor!r}")
    if body.graph_store not in GRAPH_STORES:
        errors.append(f"unknown graph_store {body.graph_store!r}")
    if body.retrieval_strategy not in RETRIEVERS:
        errors.append(f"unknown retrieval_strategy {body.retrieval_strategy!r}")
    if body.provider not in KNOWN_PROVIDERS:
        errors.append(f"unknown provider {body.provider!r}")
    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    config = PipelineConfiguration(
        name=body.name,
        description=body.description,
        extractor=body.extractor,
        graph_store=body.graph_store,
        retrieval_strategy=body.retrieval_strategy,
        ontology_version=body.ontology_version,
        provider=body.provider,
        params=body.params,
    )
    try:
        created = await asyncio.to_thread(
            insert_pipeline_configuration,
            settings.database_url,
            config=config,
            workspace_id=str(workspace_id),
        )
    except psycopg.errors.UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail=f"configuration {body.name} v{config.version} already exists; bump the name/version",
        )
    return JSONResponse(created, status_code=201)
