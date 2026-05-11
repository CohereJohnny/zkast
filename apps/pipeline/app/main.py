"""FastAPI application entry."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.deps_checks import readiness_report

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
    settings = get_settings()
    _configure_logging()
    _maybe_configure_otel(settings, app)
    app.state.settings = settings
    logger.info(
        "pipeline_start",
        version=settings.pipeline_version,
        otel_enabled=settings.zkast_otel_enabled,
    )
    yield
    logger.info("pipeline_stop")


app = FastAPI(
    title="zkast pipeline",
    version="0.0.1",
    lifespan=lifespan,
    openapi_url="/openapi.json",
)


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
    return {
        "pipeline": settings.pipeline_version,
        "contract": settings.api_contract_version,
        "graphiti": None,
    }


@app.post("/internal/v1/ingestion-runs")
async def stub_ingestion_runs() -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={"error": {"code": "not_implemented", "message": "Sprint 3+"}},
    )


@app.post("/internal/v1/persistence-jobs")
async def stub_persistence_jobs() -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={"error": {"code": "not_implemented", "message": "Sprint 7+"}},
    )


@app.post("/internal/v1/chat/turns")
async def stub_chat_turns() -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={"error": {"code": "not_implemented", "message": "Sprint 6+"}},
    )


@app.post("/internal/v1/graph/search")
async def stub_graph_search() -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={"error": {"code": "not_implemented", "message": "Sprint 5+"}},
    )
