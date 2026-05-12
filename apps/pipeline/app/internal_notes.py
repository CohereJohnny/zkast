"""Internal HTTP routes for atomic notes (web tier proxy target)."""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import Settings
from app.notes_repo import (
    add_note_link,
    delete_note,
    delete_note_link,
    fetch_note_detail,
    insert_note,
    list_notes,
    merge_notes,
    split_note,
    update_note,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["internal-notes"])


def _serialize_note(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in dict(row).items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    if out.get("id") is not None:
        out["id"] = str(out["id"])
    if out.get("workspace_id") is not None:
        out["workspace_id"] = str(out["workspace_id"])
    if out.get("created_by_user_id") is not None:
        out["created_by_user_id"] = str(out["created_by_user_id"])
    return out


def _serialize_note_link(row: dict[str, Any]) -> dict[str, Any]:
    """note_links rows include created_at from DB — must be JSON-safe."""
    out = dict(row)
    ca = out.get("created_at")
    if isinstance(ca, datetime):
        out["created_at"] = ca.isoformat()
    elif isinstance(ca, date):
        out["created_at"] = ca.isoformat()
    return out


class ManualNoteBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(default="", max_length=10000)
    tags: list[str] = Field(default_factory=list)


class PatchNoteBody(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=10000)
    tags: list[str] | None = None


class MergeNoteBody(BaseModel):
    other_note_id: uuid.UUID
    field_selection: dict[str, Literal["survivor", "other"]] = Field(
        default_factory=lambda: {"title": "survivor", "body": "survivor", "tags": "survivor"},
    )


class SplitNoteBody(BaseModel):
    passage: str = Field(..., min_length=1)
    new_title: str = Field(..., min_length=1, max_length=200)


class AddLinkBody(BaseModel):
    target_note_id: uuid.UUID
    kind: str = "related"
    custom_label: str | None = None


@router.get("/internal/v1/notes")
async def list_internal_notes(
    request: Request,
    workspace_id: Annotated[uuid.UUID, Query()],
    q: Annotated[str | None, Query()] = None,
    document_id: Annotated[str | None, Query()] = None,
    origin: Annotated[str | None, Query()] = None,
    is_user_edited: Annotated[bool | None, Query()] = None,
    tags: Annotated[list[str] | None, Query()] = None,
    sort: Annotated[str, Query()] = "updated_at_desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    rows, total = list_notes(
        settings.database_url,
        workspace_id=ws,
        q=q,
        tags=tags,
        document_id=document_id,
        origin=origin,
        is_user_edited=is_user_edited,
        limit=limit,
        offset=offset,
        sort=sort,
    )
    return JSONResponse(
        content={
            "items": [_serialize_note(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    )


@router.post("/internal/v1/notes")
async def create_internal_note(
    request: Request,
    workspace_id: Annotated[uuid.UUID, Query()],
    body: ManualNoteBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    bypass = os.environ.get("BYPASS_USER_ID")
    nid = str(uuid.uuid4())
    row = insert_note(
        settings.database_url,
        note_id=nid,
        workspace_id=ws,
        title=body.title,
        body=body.body,
        tags=body.tags,
        origin="manual",
        created_by_user_id=bypass,
        episode_ids=[],
        is_user_edited=False,
    )
    return JSONResponse(status_code=201, content={"note": _serialize_note(row)})


@router.get("/internal/v1/notes/{note_id}")
async def get_internal_note(
    note_id: uuid.UUID,
    request: Request,
    workspace_id: Annotated[uuid.UUID, Query()],
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    detail = fetch_note_detail(settings.database_url, workspace_id=str(workspace_id), note_id=str(note_id))
    if not detail:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Note not found"}})
    out = _serialize_note({k: v for k, v in detail.items() if k not in ("links_out", "links_in", "source_episodes")})
    out["links_out"] = [_serialize_note_link(dict(r)) for r in detail["links_out"]]
    out["links_in"] = [_serialize_note_link(dict(r)) for r in detail["links_in"]]
    out["source_episodes"] = [dict(r) for r in detail["source_episodes"]]
    return JSONResponse(content=out)


@router.patch("/internal/v1/notes/{note_id}")
async def patch_internal_note(
    note_id: uuid.UUID,
    request: Request,
    workspace_id: Annotated[uuid.UUID, Query()],
    body: PatchNoteBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    row = update_note(
        settings.database_url,
        workspace_id=str(workspace_id),
        note_id=str(note_id),
        title=body.title,
        body=body.body,
        tags=body.tags,
        mark_user_edited=True,
    )
    if not row:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Note not found"}})
    return JSONResponse(content={"note": _serialize_note(row)})


@router.delete("/internal/v1/notes/{note_id}")
async def delete_internal_note(
    note_id: uuid.UUID,
    request: Request,
    workspace_id: Annotated[uuid.UUID, Query()],
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ok = delete_note(settings.database_url, workspace_id=str(workspace_id), note_id=str(note_id))
    if not ok:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Note not found"}})
    return JSONResponse(content={"deleted": True})


@router.post("/internal/v1/notes/{note_id}/merge")
async def merge_internal_note(
    note_id: uuid.UUID,
    request: Request,
    workspace_id: Annotated[uuid.UUID, Query()],
    body: MergeNoteBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    merged = merge_notes(
        settings.database_url,
        workspace_id=str(workspace_id),
        survivor_note_id=str(note_id),
        other_note_id=str(body.other_note_id),
        field_selection=body.field_selection,
    )
    if not merged:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Note not found"}})
    return JSONResponse(content={"note": _serialize_note(merged)})


@router.post("/internal/v1/notes/{note_id}/split")
async def split_internal_note(
    note_id: uuid.UUID,
    request: Request,
    workspace_id: Annotated[uuid.UUID, Query()],
    body: SplitNoteBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    bypass = os.environ.get("BYPASS_USER_ID")
    try:
        new_note = split_note(
            settings.database_url,
            workspace_id=str(workspace_id),
            parent_note_id=str(note_id),
            passage=body.passage,
            new_title=body.new_title,
            bypass_user_id=bypass,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "validation_failed", "message": str(exc)}},
        ) from exc
    return JSONResponse(status_code=201, content={"note": _serialize_note(new_note)})


@router.post("/internal/v1/notes/{note_id}/links")
async def add_internal_note_link(
    note_id: uuid.UUID,
    request: Request,
    workspace_id: Annotated[uuid.UUID, Query()],
    body: AddLinkBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    try:
        link = add_note_link(
            settings.database_url,
            workspace_id=str(workspace_id),
            source_note_id=str(note_id),
            target_note_id=str(body.target_note_id),
            kind=body.kind,
            custom_label=body.custom_label,
            origin="manual",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "validation_failed", "message": str(exc)}},
        ) from exc
    return JSONResponse(status_code=201, content={"link": link})


@router.delete("/internal/v1/notes/{note_id}/links/{link_id}")
async def delete_internal_note_link(
    note_id: uuid.UUID,
    link_id: uuid.UUID,
    request: Request,
    workspace_id: Annotated[uuid.UUID, Query()],
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ok = delete_note_link(settings.database_url, workspace_id=str(workspace_id), link_id=str(link_id))
    if not ok:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Link not found"}})
    return JSONResponse(content={"deleted": True})
