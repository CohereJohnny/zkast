"""Internal HTTP API for LLM Wiki memory.

Mirrors the shape of ``internal_north.py`` for dream-jobs/dream-mutations and
adds list/detail endpoints for wiki spaces and pages.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.job_redis import job_hset, publish_job_event
from app.north_repo import fetch_north_agent
from app.wiki_repo import (
    fetch_wiki_page,
    fetch_wiki_page_sources,
    fetch_wiki_space,
    fetch_wiki_job,
    insert_wiki_job,
    list_wiki_job_mutations,
    list_wiki_pages,
    list_wiki_spaces,
    upsert_agent_wiki_space,
    upsert_default_wiki_space,
)


logger = structlog.get_logger(__name__)
router = APIRouter()


def _bad_request(msg: str) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"error": {"code": "bad_request", "message": msg}},
    )


def _not_found(thing: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"error": {"code": "not_found", "message": thing}},
    )


@router.get("/internal/v1/workspaces/{workspace_id}/wiki-spaces")
async def list_wiki_spaces_endpoint(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    items = list_wiki_spaces(settings.database_url, workspace_id=str(workspace_id))
    return JSONResponse(content={"items": items, "count": len(items)})


@router.post("/internal/v1/workspaces/{workspace_id}/wiki-spaces")
async def upsert_wiki_space_endpoint(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    """Create (or return) a wiki space for the workspace or one agent.

    Body shape (all optional):
      { "scope_kind": "workspace" | "agent", "agent_id": "...", "name": "..." }
    Workspace-wide is the default.
    """
    settings: Settings = request.app.state.settings
    body = (await request.json()) if request.headers.get("content-length") else {}
    if not isinstance(body, dict):
        body = {}
    scope_kind = str(body.get("scope_kind") or "workspace").strip().lower()
    name = body.get("name")
    if scope_kind == "workspace":
        space = upsert_default_wiki_space(
            settings.database_url,
            workspace_id=str(workspace_id),
            name=name if isinstance(name, str) else None,
        )
        return JSONResponse(status_code=200, content=space)
    if scope_kind == "agent":
        agent_id = body.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise _bad_request("agent_id is required for scope_kind=agent")
        # Validate agent exists in this workspace.
        agent = fetch_north_agent(
            settings.database_url, workspace_id=str(workspace_id), agent_id=agent_id
        )
        if not agent:
            raise _not_found("agent")
        space = upsert_agent_wiki_space(
            settings.database_url,
            workspace_id=str(workspace_id),
            agent_id=agent_id,
            name=name if isinstance(name, str) else None,
        )
        return JSONResponse(status_code=200, content=space)
    raise _bad_request(f"unsupported scope_kind '{scope_kind}'")


@router.get("/internal/v1/workspaces/{workspace_id}/wiki-spaces/{space_id}")
async def get_wiki_space(
    workspace_id: uuid.UUID,
    space_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    space = fetch_wiki_space(
        settings.database_url,
        workspace_id=str(workspace_id),
        space_id=str(space_id),
    )
    if not space:
        raise _not_found("wiki_space")
    pages = list_wiki_pages(settings.database_url, wiki_space_id=str(space_id))
    return JSONResponse(content={"space": space, "pages": pages})


@router.get("/internal/v1/workspaces/{workspace_id}/wiki-spaces/{space_id}/pages/{slug}")
async def get_wiki_page(
    workspace_id: uuid.UUID,
    space_id: uuid.UUID,
    slug: str,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    space = fetch_wiki_space(
        settings.database_url,
        workspace_id=str(workspace_id),
        space_id=str(space_id),
    )
    if not space:
        raise _not_found("wiki_space")
    page = fetch_wiki_page(
        settings.database_url,
        wiki_space_id=str(space_id),
        slug=slug,
    )
    if not page:
        raise _not_found("wiki_page")
    sources = fetch_wiki_page_sources(settings.database_url, wiki_page_id=page["id"])
    return JSONResponse(content={"page": page, "sources": sources, "space": space})


@router.post("/internal/v1/workspaces/{workspace_id}/wiki-spaces/{space_id}/generate")
async def post_generate_wiki(
    workspace_id: uuid.UUID,
    space_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    space = fetch_wiki_space(
        settings.database_url,
        workspace_id=str(workspace_id),
        space_id=str(space_id),
    )
    if not space:
        raise _not_found("wiki_space")
    job_id = insert_wiki_job(
        settings.database_url,
        workspace_id=str(workspace_id),
        wiki_space_id=str(space_id),
        kind="generate",
    )
    redis = request.app.state.redis_async
    await job_hset(
        redis,
        job_id,
        workspace_id=str(workspace_id),
        wiki_space_id=str(space_id),
        kind="wiki_generation",
        status="queued",
        progress='{"percent":0,"stage":"queued"}',
    )
    await publish_job_event(redis, job_id, "stage_started", stage="wiki_generation")
    pool = request.app.state.arq_pool
    await pool.enqueue_job(
        "run_wiki_generation_job",
        workspace_id=str(workspace_id),
        wiki_space_id=str(space_id),
        job_id=job_id,
        _job_id=f"wiki:{space_id}:{job_id}",
    )
    return JSONResponse(
        status_code=202,
        content={"enqueued": True, "job_id": job_id},
    )


@router.get("/internal/v1/workspaces/{workspace_id}/wiki-jobs/{job_id}")
async def get_wiki_job(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    job = fetch_wiki_job(
        settings.database_url,
        workspace_id=str(workspace_id),
        job_id=str(job_id),
    )
    if not job:
        raise _not_found("wiki_job")
    mutations = list_wiki_job_mutations(
        settings.database_url, wiki_job_id=str(job_id)
    )
    return JSONResponse(content={"job": job, "mutations": mutations})
