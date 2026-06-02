"""Internal routes for LLM provider configuration + connectivity tests."""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.providers import (
    KNOWN_PROVIDERS,
    ProviderError,
    probe_provider_async,
    resolve_provider,
)
from app.workspace_repo import touch_api_key_last_used

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["internal-providers"])


@router.get("/internal/v1/workspaces/{workspace_id}/providers")
async def list_providers_route(workspace_id: uuid.UUID, request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    items = []
    for spec in KNOWN_PROVIDERS.values():
        entry: dict[str, object] = {
            "id": spec.id,
            "label": spec.label,
            "supports_rerank": spec.supports_rerank,
            "default_chat_model": spec.default_chat_model,
            "default_embed_model": spec.default_embed_model,
            "base_url_required": spec.base_url_required,
            "api_key_kind": spec.api_key_kind,
        }
        try:
            cfg = await asyncio.to_thread(
                resolve_provider, settings, workspace_id=ws, provider=spec.id
            )
            entry.update(
                configured=True,
                base_url=cfg.base_url,
                chat_model=cfg.chat_model,
                embed_model=cfg.embed_model,
            )
        except ProviderError as exc:
            entry.update(configured=False, reason=str(exc))
        items.append(entry)
    return JSONResponse({"items": items})


@router.post("/internal/v1/workspaces/{workspace_id}/providers/{provider}/test")
async def test_provider_route(
    workspace_id: uuid.UUID, provider: str, request: Request
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    ws = str(workspace_id)
    try:
        cfg = await asyncio.to_thread(resolve_provider, settings, workspace_id=ws, provider=provider)
    except ProviderError as exc:
        return JSONResponse(
            {"ok": False, "error": {"code": "not_configured", "message": str(exc)}}
        )

    ok, err, stage = await probe_provider_async(cfg)
    if ok:
        spec = KNOWN_PROVIDERS.get(provider)
        if spec and spec.api_key_kind:
            await asyncio.to_thread(
                touch_api_key_last_used, settings.database_url, ws, spec.api_key_kind
            )
        return JSONResponse(
            {"ok": True, "chat_model": cfg.chat_model, "embed_model": cfg.embed_model}
        )
    return JSONResponse(
        {
            "ok": False,
            "error": {"code": "provider_error", "message": err or "probe failed", "stage": stage},
        }
    )
