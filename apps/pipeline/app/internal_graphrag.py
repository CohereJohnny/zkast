"""Internal routes to trigger + inspect MS GraphRAG batch indexes.

The actual indexing runs on the dedicated graphrag-worker; these routes (served
by the main pipeline) insert a pending ``graphrag_indexes`` row and enqueue the
job onto the graphrag queue. No graphrag import here.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.graphrag_index_repo import (
    fetch_graphrag_index,
    insert_graphrag_index,
    list_graphrag_indexes,
)
from app.queues import GRAPHRAG_QUEUE_NAME

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["internal-graphrag"])

EMBED_DIM = 1536


class GraphragIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: uuid.UUID | None = None
    configuration_id: uuid.UUID | None = None
    provider: str = "cohere_compat"
    ontology_name: str | None = None
    ontology_version: str | None = None
    max_docs: int | None = Field(default=None, ge=1, le=5000)


@router.post("/internal/v1/workspaces/{workspace_id}/graphrag/index")
async def start_graphrag_index_route(
    workspace_id: uuid.UUID, body: GraphragIndexRequest, request: Request
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    pool = request.app.state.arq_pool
    ws = str(workspace_id)

    created = await asyncio.to_thread(
        insert_graphrag_index,
        settings.database_url,
        workspace_id=ws,
        agent_id=str(body.agent_id) if body.agent_id else None,
        configuration_id=str(body.configuration_id) if body.configuration_id else None,
        provider=body.provider,
        embedding_dim=EMBED_DIM,
        ontology_name=body.ontology_name,
        ontology_version=body.ontology_version,
    )
    index_id = created["id"]

    enqueued = await pool.enqueue_job(
        "run_graphrag_index_job",
        index_id=index_id,
        workspace_id=ws,
        agent_id=str(body.agent_id) if body.agent_id else None,
        configuration_id=str(body.configuration_id) if body.configuration_id else None,
        ontology_name=body.ontology_name,
        ontology_version=body.ontology_version,
        max_docs=body.max_docs,
        _job_id=f"graphrag:{index_id}",
        _queue_name=GRAPHRAG_QUEUE_NAME,
    )
    if enqueued is None:
        raise HTTPException(status_code=409, detail="GraphRAG index job already enqueued")

    return JSONResponse({"index_id": index_id, "status": "pending"}, status_code=202)


@router.get("/internal/v1/workspaces/{workspace_id}/graphrag/indexes")
async def list_graphrag_indexes_route(workspace_id: uuid.UUID, request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    items = await asyncio.to_thread(
        list_graphrag_indexes, settings.database_url, workspace_id=str(workspace_id)
    )
    return JSONResponse({"items": items})


@router.get("/internal/v1/workspaces/{workspace_id}/graphrag/indexes/{index_id}")
async def get_graphrag_index_route(
    workspace_id: uuid.UUID, index_id: uuid.UUID, request: Request
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    row = await asyncio.to_thread(
        fetch_graphrag_index, settings.database_url, index_id=str(index_id)
    )
    if row is None or row.get("workspace_id") != str(workspace_id):
        raise HTTPException(status_code=404, detail="GraphRAG index not found")
    return JSONResponse(row)
