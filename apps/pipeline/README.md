# zkast pipeline (FastAPI)

Python **3.12** service for ingestion, Graphiti, and chat orchestration (stubs in Sprint 1).

## Prerequisites

- Python **3.12** recommended (`pyenv`, `uv`, or system)
- Running **Postgres**, **Redis**, and **FalkorDB** if you want `/readyz` fully green (see root `docker-compose.yml`)

## Local development

```bash
cd apps/pipeline
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export DATABASE_URL=postgresql://zkast:zkast@localhost:5432/zkast
export REDIS_URL=redis://localhost:6379/0
export FALKORDB_HOST=localhost
export FALKORDB_PORT=6379
export INTERNAL_PIPELINE_TOKEN=dev-token
export MASTER_ENCRYPTION_KEY="$(openssl rand -base64 32)"

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- OpenAPI: `http://localhost:8000/openapi.json`
- Health: `GET /healthz`, readiness: `GET /readyz`, version: `GET /version`

## Tests

From repository root:

```bash
pnpm run test:pipeline
```

Or here with a venv (use `python -m pytest` so you do not need a global `pytest` on `PATH`):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export MASTER_ENCRYPTION_KEY="$(openssl rand -base64 32)"
python -m pytest
```

Uses `MASTER_ENCRYPTION_KEY` from env for AES-GCM roundtrip smoke (`tests/test_secrets.py`).

## Telemetry

Set `ZKAST_OTEL_ENABLED=true` to register tracing + FastAPI instrumentation (console exporter in Sprint 1). Default **false** (**NFR-2**).
