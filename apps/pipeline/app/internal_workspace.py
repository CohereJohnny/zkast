"""Workspace lifecycle — baseline reset for controlled E2E testing."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.workspace_reset import (
    WorkspaceResetBusyError,
    preview_workspace_reset,
    purge_workspace_graphiti,
    purge_workspace_redis_jobs,
    purge_workspace_storage,
    reset_workspace_postgres,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["internal-workspace"])


class ResetWorkspaceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str = Field(
        ...,
        description='Must be exactly "RESET" to authorize destructive wipe.',
    )
    force: bool = Field(
        default=False,
        description="Cancel in-flight ingestion/dream/wiki jobs, then wipe.",
    )
    purge_graphiti: bool = Field(default=True)
    purge_storage: bool = Field(default=True)
    purge_redis_jobs: bool = Field(default=True)


@router.get("/internal/v1/workspaces/{workspace_id}/reset/preview")
async def get_workspace_reset_preview(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    preview = await asyncio.to_thread(
        preview_workspace_reset,
        settings.database_url,
        workspace_id=str(workspace_id),
    )
    return JSONResponse(content=preview.to_dict())


@router.post("/internal/v1/workspaces/{workspace_id}/reset")
async def post_workspace_reset(
    workspace_id: uuid.UUID,
    request: Request,
    body: ResetWorkspaceBody,
) -> JSONResponse:
    if body.confirm.strip() != "RESET":
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "confirmation_required",
                    "message": 'Type confirm="RESET" to wipe workspace content.',
                }
            },
        )

    settings: Settings = request.app.state.settings
    ws = str(workspace_id)

    try:
        postgres_deleted, preview = await asyncio.to_thread(
            reset_workspace_postgres,
            settings.database_url,
            workspace_id=ws,
            force=body.force,
        )
    except WorkspaceResetBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "workspace_busy",
                    "message": "Active jobs are still running. Use force=true to cancel and reset.",
                    "reasons": exc.reasons,
                }
            },
        ) from exc

    result: dict[str, Any] = {
        "workspace_id": ws,
        "postgres": postgres_deleted,
        "redis_jobs_deleted": 0,
        "graphiti_deleted": False,
        "storage_cleared": False,
        "preview_before": preview.counts,
    }

    if body.purge_redis_jobs:
        redis = request.app.state.redis_async
        result["redis_jobs_deleted"] = await purge_workspace_redis_jobs(
            redis, workspace_id=ws
        )

    if body.purge_graphiti:
        try:
            result["graphiti_deleted"] = await purge_workspace_graphiti(
                falkordb_host=settings.falkordb_host,
                falkordb_port=settings.falkordb_port,
                workspace_id=ws,
                database_url=settings.database_url,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("workspace_reset_graphiti", workspace_id=ws, err=str(exc))
            result["graphiti_deleted"] = False
            result["graphiti_error"] = str(exc)

    if body.purge_storage:
        result["storage_cleared"] = await asyncio.to_thread(
            purge_workspace_storage,
            settings.zkast_storage_root,
            workspace_id=ws,
        )

    logger.info("workspace_reset_complete", workspace_id=ws, summary=result)
    return JSONResponse(content=result)
