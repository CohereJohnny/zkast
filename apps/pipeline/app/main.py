"""FastAPI application entry."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as pkg_version
from uuid import UUID

import redis.asyncio as aioredis
import structlog
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from app.cohere_probe import probe_cohere_async
from app.config import Settings, get_settings
from app.deps_checks import readiness_report
from app.graphiti_factory import resolve_stored_cohere_api_key
from app.internal_admin import router as internal_admin_router
from app.internal_chat import router as internal_chat_router
from app.internal_eval import router as internal_eval_router
from app.internal_graph import router as internal_graph_router
from app.internal_ingestion import router as internal_ingestion_router
from app.internal_jobs import router as internal_jobs_router
from app.internal_north import router as internal_north_router
from app.internal_slack import router as internal_slack_router
from app.internal_notes import router as internal_notes_router
from app.internal_wiki import router as internal_wiki_router
from app.internal_dashboard import router as internal_dashboard_router
from app.internal_workspace import router as internal_workspace_router
from app.internal_prompt_sets import router as internal_prompt_sets_router
from app.internal_providers import router as internal_providers_router
from app.internal_graphrag import router as internal_graphrag_router
from app.internal_pipelines import router as internal_pipelines_router
from app.workspace_repo import fetch_pipeline_settings, merge_pipeline_settings, touch_llm_cohere_last_used

logger = structlog.get_logger(__name__)


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),
        cache_logger_on_first_use=True,
    )


def _maybe_configure_otel(settings: Settings, app: FastAPI) -> None:
    if not settings.zkast_otel_enabled:
        return
    from opentelemetry import trace
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    resource = Resource.create({"service.name": "zkast-pipeline"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    os.environ.setdefault("GRAPHITI_TELEMETRY_ENABLED", "false")
    settings = get_settings()
    _configure_logging()
    _maybe_configure_otel(settings, app)
    app.state.settings = settings
    app.state.redis_async = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    logger.info(
        "pipeline_start",
        version=settings.pipeline_version,
        otel_enabled=settings.zkast_otel_enabled,
    )
    yield
    await app.state.arq_pool.close()
    await app.state.redis_async.aclose()
    logger.info("pipeline_stop")


app = FastAPI(
    title="zkast pipeline",
    version="0.0.1",
    lifespan=lifespan,
    openapi_url="/openapi.json",
)

app.include_router(internal_ingestion_router)
app.include_router(internal_north_router)
app.include_router(internal_slack_router)
app.include_router(internal_jobs_router)
app.include_router(internal_notes_router)
app.include_router(internal_graph_router)
app.include_router(internal_admin_router)
app.include_router(internal_chat_router)
app.include_router(internal_eval_router)
app.include_router(internal_wiki_router)
app.include_router(internal_workspace_router)
app.include_router(internal_dashboard_router)
app.include_router(internal_prompt_sets_router)
app.include_router(internal_providers_router)
app.include_router(internal_graphrag_router)
app.include_router(internal_pipelines_router)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    rid = request.headers.get("x-request-id") or str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(request_id=rid)
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    structlog.contextvars.clear_contextvars()
    return response


@app.middleware("http")
async def internal_guard(request: Request, call_next):  # type: ignore[no-untyped-def]
    if request.url.path.startswith("/internal"):
        settings: Settings = request.app.state.settings
        token = request.headers.get("x-zkast-internal-token")
        if token != settings.internal_pipeline_token:
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "forbidden", "message": "Invalid internal token"}},
            )
    return await call_next(request)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    return readiness_report(settings)


@app.get("/version")
async def version(request: Request) -> dict[str, str | None]:
    settings: Settings = request.app.state.settings
    try:
        gv = pkg_version("graphiti-core")
    except PackageNotFoundError:
        gv = None
    return {
        "pipeline": settings.pipeline_version,
        "contract": settings.api_contract_version,
        "graphiti": gv,
    }


class CohereTestBody(BaseModel):
    workspace_id: UUID | None = None
    api_key: str | None = Field(default=None, min_length=8)

    @model_validator(mode="after")
    def require_target(self) -> CohereTestBody:
        if self.workspace_id is None and self.api_key is None:
            raise ValueError("Provide workspace_id and/or api_key")
        return self


@app.post("/internal/v1/providers/cohere/test")
async def internal_cohere_test(body: CohereTestBody, request: Request) -> dict[str, object]:
    settings: Settings = request.app.state.settings
    ws_id = str(body.workspace_id) if body.workspace_id else None

    if body.api_key:
        key = body.api_key
        pipe = (
            fetch_pipeline_settings(settings.database_url, ws_id)
            if ws_id
            else merge_pipeline_settings(None)
        )
    elif ws_id:
        key = resolve_stored_cohere_api_key(settings, ws_id)
        if not key:
            return {
                "ok": False,
                "error": {
                    "code": "no_key",
                    "message": "No llm_cohere API key stored for this workspace",
                },
            }
        pipe = fetch_pipeline_settings(settings.database_url, ws_id)
    else:
        return {
            "ok": False,
            "error": {"code": "validation_failed", "message": "Provide workspace_id or api_key"},
        }

    ok, err, stage = await probe_cohere_async(
        key,
        chat_model=str(pipe["large_model"]),
        embed_model=str(pipe["embed_model"]),
        rerank_model=str(pipe["rerank_model"]),
    )
    used_stored_key = ws_id is not None and body.api_key is None
    if ok and used_stored_key:
        touch_llm_cohere_last_used(settings.database_url, ws_id)

    if not ok:
        return {
            "ok": False,
            "error": {
                "code": "provider_error",
                "message": err or "Cohere probe failed",
                "stage": stage,
            },
        }
    return {"ok": True}


@app.post("/internal/v1/persistence-jobs")
async def stub_persistence_jobs() -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={"error": {"code": "not_implemented", "message": "Sprint 7+"}},
    )


# Sprint 6 — removed `POST /internal/v1/chat/turns` 501 stub.
# Grounded chat is now served by the workspace-scoped routes in
# ``app.internal_chat``:
#   POST /internal/v1/workspaces/{ws}/chat-sessions/{id}/messages
#   POST /internal/v1/workspaces/{ws}/chat/turns/{turn_id}/cancel
# See [specs/apis.md](../../specs/apis.md) Internal Contract section.


# Sprint 5b — removed `POST /internal/v1/graph/search` stub (HTTP 501).
# Hybrid search is now served by the workspace-scoped
# `GET /internal/v1/workspaces/{workspaceId}/graph/search` route in
# ``app.internal_graph``. See [specs/apis.md](../../specs/apis.md) Internal
# Contract section.
