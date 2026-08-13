"""Internal document collection APIs (memory-space peers)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.collections_repo import (
    create_collection,
    fetch_collection,
    list_collections,
    list_document_ids_for_collection,
)
from app.config import Settings
from psycopg.errors import UniqueViolation

router = APIRouter(tags=["internal-collections"])


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in dict(row).items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    for k in ("id", "workspace_id"):
        if out.get(k) is not None:
            out[k] = str(out[k])
    return out


class CollectionCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


@router.get("/internal/v1/workspaces/{workspace_id}/document-collections")
async def list_document_collections(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    rows = list_collections(
        settings.database_url, workspace_id=str(workspace_id)
    )
    return JSONResponse({"items": [_serialize(r) for r in rows]})


@router.post("/internal/v1/workspaces/{workspace_id}/document-collections")
async def post_document_collection(
    workspace_id: uuid.UUID,
    body: CollectionCreateBody,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    try:
        row = create_collection(
            settings.database_url,
            workspace_id=str(workspace_id),
            name=body.name,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "validation_failed",
                    "message": str(exc).replace("_", " "),
                }
            },
        ) from exc
    except UniqueViolation as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "conflict",
                    "message": "A collection with that name already exists",
                }
            },
        ) from exc
    return JSONResponse({"collection": _serialize(row)}, status_code=201)


@router.get("/internal/v1/workspaces/{workspace_id}/document-collections/{collection_id}")
async def get_document_collection(
    workspace_id: uuid.UUID,
    collection_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    row = fetch_collection(
        settings.database_url,
        workspace_id=str(workspace_id),
        collection_id=str(collection_id),
    )
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Collection not found"}},
        )
    doc_ids = list_document_ids_for_collection(
        settings.database_url,
        workspace_id=str(workspace_id),
        collection_id=str(collection_id),
    )
    payload = _serialize(row)
    payload["document_ids"] = doc_ids
    return JSONResponse({"collection": payload})
