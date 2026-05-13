"""Sprint 6b — internal routes for the chat-eval / retrieval-mode UI.

Wraps two things:

1. Naive-RAG raw-chunk index management (backfill + status).
2. Chat eval-run lifecycle: list runs, fetch run details, kick off a
   new run.

The eval runner is intentionally blocking (Cohere streaming per
question), so for a real dataset it runs over many minutes. The HTTP
handler runs it in a background task and the UI polls
``GET .../eval/runs/{run_id}`` for status.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import psycopg
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from app import raw_chunk_index
from app.config import Settings
from app.eval.runner import run_eval as _run_eval_async
from app.graphiti_factory import resolve_cohere_api_key

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["internal-eval"])


# -----------------------------------------------------------------------------
# Naive-RAG raw-chunk index
# -----------------------------------------------------------------------------


class BackfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Reserved for future overrides (e.g. dimension / model). Currently
    # we use workspace pipeline settings.
    embedding_model: str | None = None


@router.get(
    "/internal/v1/workspaces/{workspace_id}/retrieval-index/status"
)
async def get_index_status(
    workspace_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    counts = await asyncio.to_thread(
        raw_chunk_index.count_raw_chunks,
        settings.database_url,
        workspace_id=str(workspace_id),
    )
    return JSONResponse(content={"raw_chunk": counts})


@router.post(
    "/internal/v1/workspaces/{workspace_id}/retrieval-index/backfill"
)
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
    summary = await raw_chunk_index.backfill_raw_chunks(
        settings.database_url,
        workspace_id=str(workspace_id),
        api_key=api_key,
        embedding_model=(body.embedding_model if body else None)
        or "embed-v4.0",
    )
    return JSONResponse(content={"summary": summary})


# -----------------------------------------------------------------------------
# Eval runs
# -----------------------------------------------------------------------------


class StartEvalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_name: str | None = Field(default=None)
    retrieval_modes: list[str] | None = Field(default=None)
    notes: str | None = Field(default=None, max_length=2000)


@router.get(
    "/internal/v1/workspaces/{workspace_id}/eval/runs"
)
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


@router.get(
    "/internal/v1/workspaces/{workspace_id}/eval/runs/{run_id}"
)
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
                question_text,
                expected_answer_patterns,
                expected_entity_ids,
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
                answer_text,
                refused,
                scores,
                latency_ms,
                tokens_in,
                tokens_out,
                created_at
            FROM chat_eval_results
            WHERE run_id = %s::uuid
            ORDER BY question_id, retrieval_mode
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


@router.post(
    "/internal/v1/workspaces/{workspace_id}/eval/runs"
)
async def start_eval_run(
    workspace_id: uuid.UUID,
    request: Request,
    body: StartEvalBody,
) -> JSONResponse:
    """Kick off an eval run in the background.

    Responds 202 with the run id; the UI polls
    ``GET .../eval/runs/{run_id}`` until ``status='complete'``.
    """
    modes = list(body.retrieval_modes or ["rag", "graph", "hybrid"])
    notes = body.notes

    async def _runner() -> None:
        try:
            await _run_eval_async(
                workspace_id=str(workspace_id),
                modes=modes,
                notes=notes,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("eval_run_failed", workspace_id=str(workspace_id), err=str(exc))

    task = asyncio.create_task(_runner())
    # Track on the FastAPI app state so the GC doesn't drop the task.
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
            "dataset_name": body.dataset_name or "oil_gas_v1",
            "retrieval_modes": modes,
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
