"""Internal routes for memory eval runs and retrieval-index management."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import psycopg
import structlog
import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from app import raw_chunk_index
from app.config import Settings
from app.eval.runner import (
    create_eval_run,
    default_modes_for_dataset,
    run_eval as _run_eval_async,
)
from app.graphiti_factory import resolve_cohere_api_key
from app.note_embedding_index import backfill_note_embeddings
from app.retrieval_embeddings_repo import count_by_kind

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["internal-eval"])

DATASETS_DIR = Path(__file__).resolve().parent / "eval" / "datasets"


# -----------------------------------------------------------------------------
# Naive-RAG raw-chunk index
# -----------------------------------------------------------------------------


class BackfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    embedding_model: str | None = None
    kinds: list[str] | None = Field(
        default=None,
        description="Index kinds: raw_chunk, note_zettel, note_amem.",
    )
    agent_id: uuid.UUID | None = None
    limit: int | None = Field(default=500, ge=1, le=5000)


@router.get("/internal/v1/workspaces/{workspace_id}/retrieval-index/status")
async def get_index_status(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    raw_counts, by_kind = await asyncio.gather(
        asyncio.to_thread(
            raw_chunk_index.count_raw_chunks,
            settings.database_url,
            workspace_id=ws,
        ),
        asyncio.to_thread(
            count_by_kind,
            settings.database_url,
            workspace_id=ws,
        ),
    )
    return JSONResponse(
        content={
            "raw_chunk": raw_counts,
            "by_kind": by_kind,
        },
    )


@router.post("/internal/v1/workspaces/{workspace_id}/retrieval-index/backfill")
async def post_backfill_index(
    workspace_id: uuid.UUID,
    request: Request,
    body: BackfillRequest | None = None,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    api_key = await asyncio.to_thread(
        resolve_cohere_api_key, settings, str(workspace_id)
    )
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "no_api_key",
                    "message": "No Cohere API key configured for this workspace.",
                }
            },
        )
    ws = str(workspace_id)
    embed_model = (body.embedding_model if body else None) or "embed-v4.0"
    kinds = (body.kinds if body and body.kinds else None) or ["raw_chunk"]
    agent_id = str(body.agent_id) if body and body.agent_id else None
    limit = body.limit if body and body.limit else 500

    summary: dict[str, Any] = {}
    if "raw_chunk" in kinds:
        summary["raw_chunk"] = await raw_chunk_index.backfill_raw_chunks(
            settings.database_url,
            workspace_id=ws,
            api_key=api_key,
            embedding_model=embed_model,
        )
    note_kinds = [k for k in kinds if k in ("note_zettel", "note_amem")]
    if note_kinds:
        summary["notes"] = await backfill_note_embeddings(
            api_key=api_key,
            database_url=settings.database_url,
            workspace_id=ws,
            embed_model=embed_model,
            kinds=note_kinds,
            agent_id=agent_id,
            limit=limit,
        )
    return JSONResponse(content={"summary": summary})


# -----------------------------------------------------------------------------
# Eval datasets catalog
# -----------------------------------------------------------------------------


@router.get("/internal/v1/eval/datasets")
async def list_eval_datasets() -> JSONResponse:
    items: list[dict[str, Any]] = []
    for path in sorted(DATASETS_DIR.glob("*.yaml")):
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        name = str(data.get("name") or path.stem)
        items.append(
            {
                "name": name,
                "file": path.name,
                "description": (data.get("description") or "").strip(),
                "question_count": len(data.get("questions") or []),
                "default_modes": default_modes_for_dataset(name),
            }
        )
    return JSONResponse(content={"items": items})


# -----------------------------------------------------------------------------
# Eval runs
# -----------------------------------------------------------------------------


class StartEvalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_name: str | None = Field(default=None)
    retrieval_modes: list[str] | None = Field(default=None)
    notes: str | None = Field(default=None, max_length=2000)
    agent_id: uuid.UUID | None = Field(default=None)
    top_k_cutoffs: list[int] | None = Field(default=None)
    run_mode: str = Field(default="full")
    eval_kind: str = Field(default="memory_system")


@router.get("/internal/v1/workspaces/{workspace_id}/eval/runs")
async def list_eval_runs(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT
                id::text AS id,
                dataset_name,
                dataset_version,
                retrieval_modes,
                status,
                notes,
                eval_kind,
                agent_id::text AS agent_id,
                top_k_cutoffs,
                run_config,
                summary,
                created_at,
                completed_at
            FROM chat_eval_runs
            WHERE workspace_id = %s::uuid
            ORDER BY created_at DESC
            LIMIT 100
            """,
            (str(workspace_id),),
        ).fetchall()
    return JSONResponse(content={"items": _serialize_rows(rows)})


@router.get("/internal/v1/workspaces/{workspace_id}/eval/runs/{run_id}")
async def get_eval_run(
    workspace_id: uuid.UUID,
    run_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        run = conn.execute(
            """
            SELECT
                id::text AS id,
                dataset_name,
                dataset_version,
                retrieval_modes,
                status,
                notes,
                eval_kind,
                agent_id::text AS agent_id,
                top_k_cutoffs,
                run_config,
                summary,
                created_at,
                completed_at
            FROM chat_eval_runs
            WHERE workspace_id = %s::uuid AND id = %s::uuid
            """,
            (str(workspace_id), str(run_id)),
        ).fetchone()
        if not run:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "not_found", "message": "Eval run not found"}},
            )
        questions = conn.execute(
            """
            SELECT
                id::text AS id,
                question_key,
                category,
                ability_type,
                question_text,
                expected_answer_patterns,
                expected_entity_ids,
                expected_source_ids,
                expected_context_patterns,
                refusal_expected,
                notes
            FROM chat_eval_questions
            WHERE run_id = %s::uuid
            ORDER BY question_key
            """,
            (str(run_id),),
        ).fetchall()
        results = conn.execute(
            """
            SELECT
                id::text AS id,
                question_id::text AS question_id,
                retrieval_mode,
                memory_system,
                top_k_cutoff,
                answer_text,
                refused,
                scores,
                retrieval_items,
                latency_ms,
                tokens_in,
                tokens_out,
                created_at
            FROM chat_eval_results
            WHERE run_id = %s::uuid
            ORDER BY question_id, retrieval_mode, top_k_cutoff
            """,
            (str(run_id),),
        ).fetchall()
    return JSONResponse(
        content={
            "run": _serialize_row(run),
            "questions": _serialize_rows(questions),
            "results": _serialize_rows(results),
        }
    )


@router.post("/internal/v1/workspaces/{workspace_id}/eval/runs")
async def start_eval_run(
    workspace_id: uuid.UUID,
    request: Request,
    body: StartEvalBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ds_key = (body.dataset_name or "oil_gas_v1").removesuffix(".yaml")
    modes = list(body.retrieval_modes or default_modes_for_dataset(ds_key))
    cutoffs = body.top_k_cutoffs or [10, 30]
    ds_path = DATASETS_DIR / f"{ds_key}.yaml"
    dataset_path = ds_path if ds_path.is_file() else None
    if not dataset_path:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "invalid_dataset", "message": f"Unknown dataset: {ds_key}"}},
        )

    with dataset_path.open("r", encoding="utf-8") as fh:
        dataset_meta = yaml.safe_load(fh) or {}

    run_config = {
        "run_mode": body.run_mode,
        "dataset_file": dataset_path.name,
    }
    run_id = await asyncio.to_thread(
        create_eval_run,
        settings.database_url,
        workspace_id=str(workspace_id),
        dataset_name=str(dataset_meta.get("name") or ds_key),
        dataset_version=str(dataset_meta.get("version") or "1"),
        modes=modes,
        notes=body.notes,
        eval_kind=body.eval_kind,
        agent_id=str(body.agent_id) if body.agent_id else None,
        top_k_cutoffs=cutoffs,
        run_config=run_config,
    )

    async def _runner() -> None:
        try:
            await _run_eval_async(
                workspace_id=str(workspace_id),
                dataset_path=dataset_path,
                modes=modes,
                notes=body.notes,
                agent_id=str(body.agent_id) if body.agent_id else None,
                run_id=run_id,
                top_k_cutoffs=cutoffs,
                run_mode=body.run_mode,
                eval_kind=body.eval_kind,
                run_config=run_config,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "eval_run_failed",
                workspace_id=str(workspace_id),
                run_id=run_id,
                err=str(exc),
            )

    task = asyncio.create_task(_runner())
    pending = getattr(request.app.state, "background_tasks", None)
    if pending is None:
        pending = set()
        request.app.state.background_tasks = pending
    pending.add(task)
    task.add_done_callback(lambda t: pending.discard(t))

    return JSONResponse(
        status_code=202,
        content={
            "status": "started",
            "run_id": run_id,
            "dataset_name": body.dataset_name or "oil_gas_v1",
            "retrieval_modes": modes,
            "top_k_cutoffs": cutoffs,
            "run_mode": body.run_mode,
        },
    )


def _serialize_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _serialize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_serialize_row(r) or {} for r in rows]
