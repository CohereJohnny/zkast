"""Workspace dashboard metrics API."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.dashboard_metrics_repo import fetch_dashboard_metrics

router = APIRouter(tags=["internal-dashboard"])


@router.get("/internal/v1/workspaces/{workspace_id}/dashboard")
async def get_workspace_dashboard(
    workspace_id: uuid.UUID,
    request: Request,
    agent_id: uuid.UUID | None = Query(default=None),
    conversation_id: str | None = Query(default=None, max_length=256),
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)

    def _load() -> dict[str, Any]:
        return fetch_dashboard_metrics(
            settings.database_url,
            workspace_id=ws,
            falkordb_host=settings.falkordb_host,
            falkordb_port=settings.falkordb_port,
            agent_id=str(agent_id) if agent_id else None,
            conversation_id=(conversation_id or "").strip() or None,
        )

    body = await asyncio.to_thread(_load)
    return JSONResponse(content=body)
