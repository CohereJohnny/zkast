"""Internal HTTP routes for working graph + snapshots."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import entities_repo
from app.cascade import cleanup_orphan_graph_rows
from app.config import Settings
from app.graph_edit_repo import (
    delete_entity,
    end_relationship,
    fetch_relationship,
    insert_manual_relationship,
    merge_entities,
    patch_entity,
    patch_relationship,
    unmerge_entity,
)
from app.evidence_repo import list_evidence_for_entity
from app.filter_options_repo import (
    list_edge_type_counts,
    list_entity_type_counts,
    list_tag_counts,
    search_entities_typeahead,
)
from app.graph_repo import get_entity_detail, list_graph
from app.graphrag_graph_repo import list_graphrag_graph
from app.graphiti_factory import graphiti_for_workspace
from app.snapshots_repo import (
    SnapshotError,
    create_snapshot,
    delete_snapshot,
    fetch_snapshot,
    list_snapshots,
    upsert_snapshot_review,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["internal-graph"])


def _parse_valid_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class PatchEntityBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    canonical_name: str | None = Field(default=None, max_length=500)
    type_: str | None = Field(default=None, max_length=120, alias="type")
    aliases: list[str] | None = None
    summary: str | None = Field(default=None, max_length=2000)
    properties: dict[str, Any] | None = None


class MergeEntityBody(BaseModel):
    other_entity_id: uuid.UUID
    field_selection: dict[str, Literal["survivor", "other"]] = Field(
        default_factory=lambda: {
            "canonical_name": "survivor",
            "type": "survivor",
            "aliases": "survivor",
            "summary": "survivor",
            "properties": "survivor",
        },
    )


class CreateRelationshipBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    rel_type: str = Field(..., min_length=1, max_length=120, alias="type")
    fact: str = Field(default="", max_length=500)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class PatchRelationshipBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    rel_type: str | None = Field(default=None, max_length=120, alias="type")
    fact: str | None = Field(default=None, max_length=500)
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class CreateSnapshotBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


@router.post("/internal/v1/workspaces/{workspace_id}/graph/cleanup-orphans")
async def internal_cleanup_orphan_graph_rows(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    """Manual cleanup of entities/relationships with no remaining provenance.

    Useful after `cascade=document_only` deletes (which intentionally leave
    derivatives alone) or to clean up legacy rows from older delete flows.
    Preserves user-edited entities and manual relationships.
    """
    settings: Settings = request.app.state.settings
    result = cleanup_orphan_graph_rows(settings.database_url, workspace_id=str(workspace_id))
    logger.info(
        "graph_cleanup_orphans",
        workspace_id=str(workspace_id),
        removed_entities=result["removed_entities"],
        removed_relationships=result["removed_relationships"],
    )
    return JSONResponse(content=result)


@router.get("/internal/v1/workspaces/{workspace_id}/graph")
async def internal_get_graph(
    workspace_id: uuid.UUID,
    request: Request,
    backend: Annotated[Literal["graphiti", "graphrag"], Query()] = "graphiti",
    graphrag_index_id: Annotated[uuid.UUID | None, Query()] = None,
    community_id: Annotated[int | None, Query()] = None,
    view: Annotated[str, Query()] = "overview",
    seed_entity_ids: Annotated[list[uuid.UUID] | None, Query()] = None,
    depth: Annotated[int, Query(ge=0, le=10)] = 2,
    entity_type: Annotated[list[str] | None, Query()] = None,
    edge_type: Annotated[list[str] | None, Query()] = None,
    document_id: Annotated[uuid.UUID | None, Query()] = None,
    agent_id: Annotated[uuid.UUID | None, Query()] = None,
    collection_id: Annotated[uuid.UUID | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
    valid_at: Annotated[str | None, Query()] = None,
    node_limit: Annotated[int, Query(ge=1, le=25000)] = 5000,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    seeds = [str(x) for x in (seed_entity_ids or [])]
    va = _parse_valid_at(valid_at)
    try:
        if backend == "graphrag":
            data = await asyncio.to_thread(
                list_graphrag_graph,
                settings.database_url,
                workspace_id=ws,
                graphrag_index_id=str(graphrag_index_id) if graphrag_index_id else None,
                agent_id=str(agent_id) if agent_id else None,
                collection_id=str(collection_id) if collection_id else None,
                community_id=community_id,
                node_limit=node_limit,
            )
        else:
            data = list_graph(
                settings.database_url,
                workspace_id=ws,
                view=view,
                seed_entity_ids=seeds or None,
                depth=depth,
                entity_types=entity_type,
                edge_types=edge_type,
                document_id=str(document_id) if document_id else None,
                tag=tag,
                agent_id=str(agent_id) if agent_id else None,
                collection_id=str(collection_id) if collection_id else None,
                valid_at=va,
                node_limit=node_limit,
            )
    except LookupError as e:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": str(e)}},
        ) from e
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "artifacts_missing", "message": str(e)}},
        ) from e
    except Exception as e:
        logger.exception("graph_list_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail={"error": {"code": "internal_error", "message": "Failed to load graph"}},
        ) from e
    return JSONResponse(content=data)


@router.get("/internal/v1/workspaces/{workspace_id}/graph/entities/{entity_id}")
async def internal_get_entity(
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    request: Request,
    neighbor_depth: Annotated[int, Query(ge=0, le=5)] = 1,
    neighbor_limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    try:
        detail = await asyncio.to_thread(
            get_entity_detail,
            settings.database_url,
            workspace_id=str(workspace_id),
            entity_id=str(entity_id),
            neighbor_depth=neighbor_depth,
            neighbor_limit=neighbor_limit,
        )
    except Exception as e:
        logger.exception("entity_detail_failed", entity_id=str(entity_id), error=str(e))
        raise HTTPException(
            status_code=500,
            detail={"error": {"code": "internal_error", "message": "Failed to load entity"}},
        ) from e
    if not detail:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Entity not found"}})
    return JSONResponse(content={"entity": detail})


@router.get("/internal/v1/workspaces/{workspace_id}/graph/types")
async def internal_list_graph_types(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    """Filter-picker data: distinct entity + edge types in this workspace.

    Sprint 5c Phase 4 — backs the entity-type / edge-type multi-select
    chips in the graph filter bar so users no longer have to know type
    names upfront.
    """
    settings: Settings = request.app.state.settings
    entity_types, edge_types = await asyncio.gather(
        asyncio.to_thread(list_entity_type_counts, settings.database_url, workspace_id=str(workspace_id)),
        asyncio.to_thread(list_edge_type_counts, settings.database_url, workspace_id=str(workspace_id)),
    )
    return JSONResponse(content={"entity_types": entity_types, "edge_types": edge_types})


@router.get("/internal/v1/workspaces/{workspace_id}/notes/tags")
async def internal_list_note_tags(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    """Filter-picker data: distinct atomic-note tags with counts."""
    settings: Settings = request.app.state.settings
    tags = await asyncio.to_thread(
        list_tag_counts, settings.database_url, workspace_id=str(workspace_id)
    )
    return JSONResponse(content={"tags": tags})


@router.get(
    "/internal/v1/workspaces/{workspace_id}/graph/entities/search-typeahead"
)
async def internal_search_entities_typeahead(
    workspace_id: uuid.UUID,
    request: Request,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> JSONResponse:
    """Typeahead search over entity names for the seed-entity picker.

    Distinct from the existing ``/graph/search`` endpoint which does a
    full Graphiti hybrid retrieval. This one is a cheap ILIKE so the
    picker stays responsive to every keystroke.
    """
    settings: Settings = request.app.state.settings
    items = await asyncio.to_thread(
        search_entities_typeahead,
        settings.database_url,
        workspace_id=str(workspace_id),
        q=q,
        limit=limit,
    )
    return JSONResponse(content={"items": items})


@router.get(
    "/internal/v1/workspaces/{workspace_id}/graph/entities/{entity_id}/evidence"
)
async def internal_list_entity_evidence(
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    """List source-grounded evidence rows linked to this entity.

    Sprint 5c Phase 3 — backs the "Evidence" tab in the entity detail
    panel. Each row is one LangExtract-extracted span with the source
    document, page, character range, and a quoted snippet.
    """
    settings: Settings = request.app.state.settings
    payload = await asyncio.to_thread(
        list_evidence_for_entity,
        settings.database_url,
        workspace_id=str(workspace_id),
        entity_id=str(entity_id),
        limit=limit,
        offset=offset,
    )
    return JSONResponse(content=payload)


@router.patch("/internal/v1/workspaces/{workspace_id}/graph/entities/{entity_id}")
async def internal_patch_entity(
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    request: Request,
    body: PatchEntityBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    row = patch_entity(
        settings.database_url,
        workspace_id=str(workspace_id),
        entity_id=str(entity_id),
        canonical_name=body.canonical_name,
        type_=body.type_,
        aliases=body.aliases,
        summary=body.summary,
        properties=body.properties,
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Entity not found or name collision"}},
        )
    return JSONResponse(content={"entity": row})


@router.post("/internal/v1/workspaces/{workspace_id}/graph/entities/{entity_id}/merge")
async def internal_merge_entity(
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    request: Request,
    body: MergeEntityBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    sel = {k: v for k, v in body.field_selection.items()}
    row = merge_entities(
        settings.database_url,
        workspace_id=str(workspace_id),
        survivor_id=str(entity_id),
        victim_id=str(body.other_entity_id),
        field_selection=sel,
    )
    if row is None:
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "business_rule_violation", "message": "Merge failed (not found or unique collision)"}},
        )
    return JSONResponse(content={"entity": row})


@router.post("/internal/v1/workspaces/{workspace_id}/graph/entities/{entity_id}/unmerge")
async def internal_unmerge_entity(
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    """Restore the most recently merged victim entity from the audit log."""
    settings: Settings = request.app.state.settings
    row = unmerge_entity(
        settings.database_url,
        workspace_id=str(workspace_id),
        survivor_id=str(entity_id),
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "not_found",
                    "message": "No merge audit row to undo for this entity",
                }
            },
        )
    return JSONResponse(content={"entity": row})


@router.delete("/internal/v1/workspaces/{workspace_id}/graph/entities/{entity_id}")
async def internal_delete_entity(
    workspace_id: uuid.UUID,
    entity_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ok = delete_entity(settings.database_url, workspace_id=str(workspace_id), entity_id=str(entity_id))
    if not ok:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Entity not found"}})
    return Response(status_code=204)


@router.post("/internal/v1/workspaces/{workspace_id}/graph/relationships")
async def internal_create_relationship(
    workspace_id: uuid.UUID,
    request: Request,
    body: CreateRelationshipBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    if body.source_entity_id == body.target_entity_id:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "validation_failed", "message": "Self-loop not allowed"}},
        )
    row = insert_manual_relationship(
        settings.database_url,
        workspace_id=str(workspace_id),
        source_entity_id=str(body.source_entity_id),
        target_entity_id=str(body.target_entity_id),
        rel_type=body.rel_type,
        fact=body.fact,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
    )
    return JSONResponse(status_code=201, content={"relationship": row})


@router.get("/internal/v1/workspaces/{workspace_id}/graph/relationships/{relationship_id}")
async def internal_get_relationship(
    workspace_id: uuid.UUID,
    relationship_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    row = fetch_relationship(settings.database_url, workspace_id=str(workspace_id), relationship_id=str(relationship_id))
    if not row:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Relationship not found"}})
    return JSONResponse(content={"relationship": row})


@router.patch("/internal/v1/workspaces/{workspace_id}/graph/relationships/{relationship_id}")
async def internal_patch_relationship(
    workspace_id: uuid.UUID,
    relationship_id: uuid.UUID,
    request: Request,
    body: PatchRelationshipBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    row = patch_relationship(
        settings.database_url,
        workspace_id=str(workspace_id),
        relationship_id=str(relationship_id),
        rel_type=body.rel_type,
        fact=body.fact,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
    )
    if not row:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Relationship not found"}})
    return JSONResponse(content={"relationship": row})


@router.delete("/internal/v1/workspaces/{workspace_id}/graph/relationships/{relationship_id}")
async def internal_end_relationship(
    workspace_id: uuid.UUID,
    relationship_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ok = end_relationship(settings.database_url, workspace_id=str(workspace_id), relationship_id=str(relationship_id))
    if not ok:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Relationship not found"}})
    return Response(status_code=204)


@router.get("/internal/v1/workspaces/{workspace_id}/snapshots")
async def internal_list_snapshots(
    workspace_id: uuid.UUID,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    items, total = list_snapshots(settings.database_url, workspace_id=str(workspace_id), limit=limit, offset=offset)
    return JSONResponse(content={"items": items, "total": total, "limit": limit, "offset": offset})


@router.post("/internal/v1/workspaces/{workspace_id}/snapshots")
async def internal_create_snapshot(
    workspace_id: uuid.UUID,
    request: Request,
    body: CreateSnapshotBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    bypass = os.environ.get("BYPASS_USER_ID")
    try:
        snap = create_snapshot(
            settings.database_url,
            workspace_id=str(workspace_id),
            name=body.name,
            description=body.description,
            created_by_user_id=bypass,
        )
    except SnapshotError as e:
        code = 409 if e.code == "conflict" else 422
        raise HTTPException(status_code=code, detail={"error": {"code": e.code, "message": e.message}}) from e
    return JSONResponse(status_code=201, content={"snapshot": snap})


@router.get("/internal/v1/workspaces/{workspace_id}/snapshots/{snapshot_id}")
async def internal_get_snapshot(
    workspace_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    row = fetch_snapshot(settings.database_url, workspace_id=str(workspace_id), snapshot_id=str(snapshot_id))
    if not row:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Snapshot not found"}})
    return JSONResponse(content={"snapshot": row})


@router.delete("/internal/v1/workspaces/{workspace_id}/snapshots/{snapshot_id}")
async def internal_delete_snapshot(
    workspace_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ok = delete_snapshot(settings.database_url, workspace_id=str(workspace_id), snapshot_id=str(snapshot_id))
    if not ok:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Snapshot not found"}})
    return Response(status_code=204)


class SnapshotReviewBody(BaseModel):
    decision: Literal["approved", "rejected"]
    notes: str | None = Field(default=None, max_length=2000)


@router.post("/internal/v1/workspaces/{workspace_id}/snapshots/{snapshot_id}/review")
async def internal_review_snapshot(
    workspace_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    request: Request,
    body: SnapshotReviewBody,
) -> JSONResponse:
    """Record an Approve / Reject decision on a snapshot.

    D4 — snapshot review workflow. Sprint 7 will surface the full
    persistence-job gating story; we ship the API + table now so chat
    citations can refer to reviewed snapshots.
    """
    settings: Settings = request.app.state.settings
    snap = fetch_snapshot(
        settings.database_url,
        workspace_id=str(workspace_id),
        snapshot_id=str(snapshot_id),
    )
    if not snap:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Snapshot not found"}},
        )
    bypass = os.environ.get("BYPASS_USER_ID")
    review = upsert_snapshot_review(
        settings.database_url,
        snapshot_id=str(snapshot_id),
        decision=body.decision,
        notes=body.notes,
        reviewed_by_user_id=bypass,
    )
    return JSONResponse(content={"review": review})


class GraphSearchResult(BaseModel):
    pass


@router.get("/internal/v1/workspaces/{workspace_id}/graph/search")
async def internal_graph_search(
    workspace_id: uuid.UUID,
    request: Request,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    """Hybrid search against Graphiti (text + vector + rerank).

    D3 — exposes Graphiti's ``search()`` so the graph filter bar can find
    seed entities by free text. Returns Graphiti edges + the corresponding
    Postgres entity IDs when available so the canvas can scope a subgraph.
    """
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    try:
        graphiti = await graphiti_for_workspace(settings, ws)
    except Exception as exc:  # noqa: BLE001
        logger.warning("graph_search_graphiti_unavailable", error=str(exc))
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "graphiti_unavailable", "message": str(exc)}},
        ) from exc

    try:
        results = await graphiti.search(query=q, group_ids=[ws], num_results=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("graph_search_failed", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail={"error": {"code": "internal_error", "message": "Graph search failed"}},
        ) from exc

    out: list[dict[str, Any]] = []
    for edge in results or []:
        src_id = await asyncio.to_thread(
            entities_repo.fetch_entity_id_for_graphiti_uuid,
            settings.database_url,
            getattr(edge, "source_node_uuid", None),
        )
        tgt_id = await asyncio.to_thread(
            entities_repo.fetch_entity_id_for_graphiti_uuid,
            settings.database_url,
            getattr(edge, "target_node_uuid", None),
        )
        out.append(
            {
                "source_entity_id": src_id,
                "target_entity_id": tgt_id,
                "type": getattr(edge, "name", None),
                "fact": getattr(edge, "fact", None),
                "uuid": str(getattr(edge, "uuid", "")) or None,
            }
        )
    return JSONResponse(content={"results": out, "query": q, "limit": limit})
