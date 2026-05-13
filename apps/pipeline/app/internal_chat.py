"""Sprint 6 — Internal HTTP routes for grounded chat.

Routes live under ``/internal/v1/workspaces/{workspaceId}/...`` to match
the Sprint 5b/5c conventions. The web BFF in ``apps/web/src/app/api/...``
proxies these endpoints with the public ``/api/v1/...`` shape.

The single arq task ``run_chat_turn`` is in
[`apps/pipeline/app/chat_turn.py`](apps/pipeline/app/chat_turn.py); this
router stays thin — Postgres reads/writes + arq enqueue.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.chat_repo import (
    create_session,
    fetch_message,
    fetch_session,
    insert_assistant_message_pending,
    insert_user_message,
    list_citations_for_message,
    list_messages_for_session,
    list_sessions,
    patch_session,
)
from app.config import Settings
from app.job_redis import job_hset
from app.retrieval_repo import fetch_retrieval_record_by_message

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["internal-chat"])


# ---------------------------------------------------------------------------
# Bodies
# ---------------------------------------------------------------------------


class CreateChatSessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    scope: dict[str, Any] | None = None
    model_settings: dict[str, Any] | None = None
    share_visibility: str | None = None
    pinned_snapshot_id: str | None = None
    created_by_user_id: str | None = None
    seed_message: str | None = Field(default=None, max_length=20_000)


class PatchChatSessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=200)
    scope: dict[str, Any] | None = None
    model_settings: dict[str, Any] | None = None
    pinned_snapshot_id: str | None = None


class PostMessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)
    author_user_id: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _enqueue_chat_turn(
    request: Request,
    *,
    workspace_id: str,
    session_id: str,
    user_message_id: str,
    assistant_message_id: str,
    turn_id: str,
) -> None:
    """Register the chat turn's job hash, then enqueue the arq task.

    ``_job_id`` uses a ``chat:`` prefix to avoid colliding with the
    ingestion stages' suffixed keys (Sprint 5b dedup lesson).
    """
    redis = request.app.state.redis_async
    pool = request.app.state.arq_pool

    await job_hset(
        redis,
        turn_id,
        workspace_id=workspace_id,
        session_id=session_id,
        assistant_message_id=assistant_message_id,
        kind="chat_turn",
        status="queued",
        progress='{"percent":0,"stage":"queued"}',
    )

    enqueued = await pool.enqueue_job(
        "run_chat_turn",
        workspace_id=workspace_id,
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        turn_id=turn_id,
        _job_id=f"chat:{turn_id}",
    )
    if enqueued is None:
        # Sprint 5b lesson — never trust arq's silent dedup-skip.
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "business_rule_violation",
                    "message": (
                        "Chat turn already in flight for this id "
                        "(arq dedup_collision)."
                    ),
                }
            },
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/internal/v1/workspaces/{workspace_id}/chat-sessions")
async def post_chat_session(
    workspace_id: uuid.UUID,
    request: Request,
    body: CreateChatSessionBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    db = settings.database_url
    ws_str = str(workspace_id)

    session = create_session(
        db,
        workspace_id=ws_str,
        title=body.title or "",
        created_by_user_id=body.created_by_user_id,
        scope=body.scope,
        share_visibility=body.share_visibility or "private",
        model_settings=body.model_settings,
        pinned_snapshot_id=body.pinned_snapshot_id,
    )

    seed_payload: dict[str, Any] | None = None
    if body.seed_message and body.seed_message.strip():
        seed_payload = await _submit_message(
            request,
            workspace_id=ws_str,
            session_id=session["id"],
            content=body.seed_message,
            author_user_id=body.created_by_user_id,
            effective_scope=session.get("scope"),
            model_used=(session.get("model_settings") or {}).get("chat_model"),
            retrieval_mode=(session.get("model_settings") or {}).get("retrieval_mode")
            or "graph",
        )

    return JSONResponse(
        status_code=201,
        content={"session": session, "first_turn": seed_payload},
    )


@router.get("/internal/v1/workspaces/{workspace_id}/chat-sessions")
async def list_chat_sessions(
    workspace_id: uuid.UUID,
    request: Request,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    pinned_snapshot_id: Annotated[uuid.UUID | None, Query()] = None,
    created_by_user_id: Annotated[uuid.UUID | None, Query()] = None,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    payload = list_sessions(
        settings.database_url,
        workspace_id=str(workspace_id),
        limit=limit,
        offset=offset,
        pinned_snapshot_id=str(pinned_snapshot_id) if pinned_snapshot_id else None,
        created_by_user_id=(
            str(created_by_user_id) if created_by_user_id else None
        ),
    )
    return JSONResponse(content=payload)


@router.get(
    "/internal/v1/workspaces/{workspace_id}/chat-sessions/{session_id}"
)
async def get_chat_session(
    workspace_id: uuid.UUID,
    session_id: uuid.UUID,
    request: Request,
    messages_limit: Annotated[int, Query(ge=0, le=500)] = 200,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    db = settings.database_url
    session = fetch_session(
        db, workspace_id=str(workspace_id), session_id=str(session_id)
    )
    if not session:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Session not found"}},
        )
    messages = list_messages_for_session(
        db, session_id=str(session_id), limit=messages_limit
    )
    # attach citations to assistant messages
    msg_with_cites: list[dict[str, Any]] = []
    for m in messages:
        if m.get("role") == "assistant":
            m["citations"] = list_citations_for_message(db, message_id=m["id"])
        else:
            m["citations"] = []
        msg_with_cites.append(m)
    return JSONResponse(content={"session": session, "messages": msg_with_cites})


@router.patch(
    "/internal/v1/workspaces/{workspace_id}/chat-sessions/{session_id}"
)
async def patch_chat_session(
    workspace_id: uuid.UUID,
    session_id: uuid.UUID,
    request: Request,
    body: PatchChatSessionBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    updated = patch_session(
        settings.database_url,
        workspace_id=str(workspace_id),
        session_id=str(session_id),
        title=body.title,
        scope=body.scope,
        model_settings=body.model_settings,
        pinned_snapshot_id=body.pinned_snapshot_id,
    )
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Session not found"}},
        )
    return JSONResponse(content={"session": updated})


@router.post(
    "/internal/v1/workspaces/{workspace_id}/chat-sessions/{session_id}/messages"
)
async def post_chat_message(
    workspace_id: uuid.UUID,
    session_id: uuid.UUID,
    request: Request,
    body: PostMessageBody,
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    db = settings.database_url
    ws_str = str(workspace_id)
    ses_str = str(session_id)

    session = fetch_session(db, workspace_id=ws_str, session_id=ses_str)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Session not found"}},
        )

    payload = await _submit_message(
        request,
        workspace_id=ws_str,
        session_id=ses_str,
        content=body.content,
        author_user_id=body.author_user_id,
        effective_scope=session.get("scope"),
        model_used=(session.get("model_settings") or {}).get("chat_model"),
        retrieval_mode=(session.get("model_settings") or {}).get("retrieval_mode")
        or "graph",
    )
    return JSONResponse(status_code=202, content=payload)


async def _submit_message(
    request: Request,
    *,
    workspace_id: str,
    session_id: str,
    content: str,
    author_user_id: str | None,
    effective_scope: dict[str, Any] | None,
    model_used: str | None,
    retrieval_mode: str,
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    db = settings.database_url

    user_msg = insert_user_message(
        db,
        session_id=session_id,
        content=content,
        author_user_id=author_user_id,
    )
    assistant_msg = insert_assistant_message_pending(
        db,
        session_id=session_id,
        parent_message_id=user_msg["id"],
        model_used=model_used,
        effective_scope=effective_scope,
        retrieval_mode=retrieval_mode,
    )

    turn_id = str(uuid4())
    await _enqueue_chat_turn(
        request,
        workspace_id=workspace_id,
        session_id=session_id,
        user_message_id=user_msg["id"],
        assistant_message_id=assistant_msg["id"],
        turn_id=turn_id,
    )

    return {
        "user_message": user_msg,
        "assistant_message": assistant_msg,
        "turn_id": turn_id,
    }


@router.post("/internal/v1/workspaces/{workspace_id}/chat/turns/{turn_id}/cancel")
async def cancel_chat_turn(
    workspace_id: uuid.UUID,
    turn_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    """Cooperative cancel — set a Redis flag the worker checks.

    Workers also surface ``asyncio.CancelledError`` (raised by arq on
    job_timeout / shutdown) — the flag is a supplementary signal a user
    can set to ask for early termination.
    """
    redis = request.app.state.redis_async
    flag_key = f"zkast:job:{turn_id}:cancel"
    try:
        await redis.set(flag_key, "1", ex=300)
    except Exception:  # noqa: BLE001
        logger.warning("chat_cancel_flag_set_failed", turn_id=str(turn_id))
    await job_hset(
        redis,
        str(turn_id),
        cancellation_requested_at=str(uuid4()),  # any non-empty marker
    )
    return JSONResponse(status_code=202, content={"turn_id": str(turn_id)})


# ---------------------------------------------------------------------------
# Read helpers shared with the web tier (retrieval inspector)
# ---------------------------------------------------------------------------


@router.get(
    "/internal/v1/workspaces/{workspace_id}/chat-messages/{message_id}/retrieval"
)
async def get_message_retrieval(
    workspace_id: uuid.UUID,
    message_id: uuid.UUID,
    request: Request,
) -> JSONResponse:
    """Return the immutable ``RetrievalRecord`` row that grounded a given
    assistant message — backs the "Show retrieved context" UI."""
    settings: Settings = request.app.state.settings
    db = settings.database_url
    msg = fetch_message(db, message_id=str(message_id))
    if not msg:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "Message not found"}},
        )
    rec = fetch_retrieval_record_by_message(db, message_id=str(message_id))
    return JSONResponse(content={"message": msg, "retrieval_record": rec})
