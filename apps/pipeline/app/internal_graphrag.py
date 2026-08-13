"""Internal routes to trigger + inspect MS GraphRAG batch indexes.

The actual indexing runs on the dedicated graphrag-worker; these routes (served
by the main pipeline) insert a pending ``graphrag_indexes`` row and enqueue the
job onto the graphrag queue. No graphrag import here.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.graphrag_graph_repo import get_graphrag_entity_detail, list_graphrag_communities
from app.graphrag_index_repo import (
    fetch_graphrag_index,
    insert_graphrag_index,
    list_graphrag_indexes,
    supersede_active_indexes,
)
from app.graphrag_reconcile import reconcile_stale_graphrag_indexes
from app.job_redis import arq_queue_snapshot, job_hset, record_log
from app.collections_repo import fetch_collection
from app.north_repo import fetch_north_agent
from app.queues import GRAPHRAG_QUEUE_NAME

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["internal-graphrag"])

EMBED_DIM = 1536


def _graphrag_job_id(index_id: str) -> str:
    return f"graphrag:{index_id}"


def _graphrag_job_title(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str | None,
    collection_id: str | None = None,
) -> str:
    if collection_id:
        coll = fetch_collection(
            database_url, workspace_id=workspace_id, collection_id=collection_id
        )
        if coll:
            return f"GraphRAG: {coll.get('name') or collection_id[:8]}"
        return f"GraphRAG: collection {collection_id[:8]}…"
    if not agent_id:
        return "GraphRAG: whole workspace"
    agent = fetch_north_agent(database_url, workspace_id=workspace_id, agent_id=agent_id)
    if not agent:
        return f"GraphRAG: {agent_id[:8]}…"
    name = (agent.get("display_name") or agent.get("external_agent_id") or agent_id).strip()
    if agent.get("provider") == "slack":
        return f"GraphRAG: #{name}"
    return f"GraphRAG: {name}"


class GraphragIndexRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
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
    redis = request.app.state.redis_async
    ws = str(workspace_id)
    agent_id = str(body.agent_id) if body.agent_id else None
    collection_id = str(body.collection_id) if body.collection_id else None
    if agent_id and collection_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "validation_failed",
                    "message": "agent_id and collection_id are mutually exclusive",
                }
            },
        )

    try:
        await asyncio.wait_for(
            reconcile_stale_graphrag_indexes(redis, settings.database_url),
            timeout=10.0,
        )
    except TimeoutError:
        logger.warning("graphrag_reconcile_timeout", workspace_id=ws)
    superseded = await asyncio.to_thread(
        supersede_active_indexes,
        settings.database_url,
        workspace_id=ws,
        agent_id=agent_id,
        collection_id=collection_id,
        reason="Superseded by a new GraphRAG build request.",
    )
    if superseded:
        logger.info(
            "graphrag_indexes_superseded",
            workspace_id=ws,
            agent_id=agent_id,
            collection_id=collection_id,
            count=superseded,
        )

    created = await asyncio.to_thread(
        insert_graphrag_index,
        settings.database_url,
        workspace_id=ws,
        agent_id=agent_id,
        collection_id=collection_id,
        configuration_id=str(body.configuration_id) if body.configuration_id else None,
        provider=body.provider,
        embedding_dim=EMBED_DIM,
        ontology_name=body.ontology_name,
        ontology_version=body.ontology_version,
    )
    index_id = created["id"]
    job_id = _graphrag_job_id(index_id)
    title = await asyncio.to_thread(
        _graphrag_job_title,
        settings.database_url,
        workspace_id=ws,
        agent_id=agent_id,
        collection_id=collection_id,
    )

    await job_hset(
        redis,
        job_id,
        workspace_id=ws,
        agent_id=agent_id,
        collection_id=collection_id,
        graphrag_index_id=index_id,
        kind="graphrag_index",
        status="queued",
        title=title,
        progress='{"percent":0,"stage":"graphrag_indexing"}',
    )
    await record_log(
        redis,
        job_id=job_id,
        level="info",
        stage="graphrag_indexing",
        message="GraphRAG index build queued",
        data={"index_id": index_id, "agent_id": agent_id, "collection_id": collection_id},
    )

    enqueued = await pool.enqueue_job(
        "run_graphrag_index_job",
        index_id=index_id,
        workspace_id=ws,
        agent_id=agent_id,
        collection_id=collection_id,
        configuration_id=str(body.configuration_id) if body.configuration_id else None,
        ontology_name=body.ontology_name,
        ontology_version=body.ontology_version,
        max_docs=body.max_docs,
        _job_id=job_id,
        _queue_name=GRAPHRAG_QUEUE_NAME,
    )
    if enqueued is None:
        raise HTTPException(status_code=409, detail="GraphRAG index job already enqueued")

    return JSONResponse(
        {"index_id": index_id, "job_id": job_id, "status": "pending"},
        status_code=202,
    )


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


@router.get("/internal/v1/workspaces/{workspace_id}/graphrag/communities")
async def list_graphrag_communities_route(
    workspace_id: uuid.UUID,
    request: Request,
    graphrag_index_id: uuid.UUID | None = Query(default=None),
    agent_id: uuid.UUID | None = Query(default=None),
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    try:
        items = await asyncio.to_thread(
            list_graphrag_communities,
            settings.database_url,
            workspace_id=str(workspace_id),
            graphrag_index_id=str(graphrag_index_id) if graphrag_index_id else None,
            agent_id=str(agent_id) if agent_id else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse({"items": items})


@router.get("/internal/v1/workspaces/{workspace_id}/graphrag/entities/{entity_id}")
async def get_graphrag_entity_route(
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    request: Request,
    graphrag_index_id: uuid.UUID | None = Query(default=None),
    agent_id: uuid.UUID | None = Query(default=None),
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    try:
        detail = await asyncio.to_thread(
            get_graphrag_entity_detail,
            settings.database_url,
            workspace_id=str(workspace_id),
            entity_id=str(entity_id),
            graphrag_index_id=str(graphrag_index_id) if graphrag_index_id else None,
            agent_id=str(agent_id) if agent_id else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not detail:
        raise HTTPException(status_code=404, detail="GraphRAG entity not found")
    return JSONResponse({"entity": detail})
