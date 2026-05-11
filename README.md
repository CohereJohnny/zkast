# zkast

**zkast** (“zettelkasten + cast”) is a planned application that ingests **PDFs**, generates **atomic Zettelkasten-style notes**, builds an **Obsidian-style knowledge graph** backed by [Graphiti](https://github.com/getzep/graphiti), and supports **grounded chat** over your corpus using **Cohere** (with citations). After review, you can **persist** snapshots to a graph database you control—**Neo4j** or **Postgres with Apache AGE**.

The product is specified as **self-hostable first** (Docker Compose, BYO Cohere key) with a path toward multi-user and SaaS later.

## Architecture (Sprint 2+)

zkast is a two-process system: **Next.js 14** (UI + public HTTP) and **FastAPI** (Graphiti, ingestion, chat orchestration). Both read the working store in **Postgres**; the pipeline talks to **FalkorDB** for the working graph and **Cohere** (Command via OpenAI-compat, Embed v3, Rerank v3) for all LLM operations in P0.

```mermaid
flowchart LR
  Web["Next.js"]
  PG[("Postgres")]
  Pipe["Pipeline FastAPI"]
  Falkor["FalkorDB"]
  Cohere["Cohere API"]
  Web -->|"REST"| PG
  Web -->|"internal token"| Pipe
  Pipe -->|"SQL"| PG
  Pipe --> Falkor
  Pipe --> Cohere
```

### Cohere API key

1. Create a key in the [Cohere dashboard](https://dashboard.cohere.com/) (production tier as appropriate).
2. At first launch, paste it in the onboarding modal or under **Settings → API keys**. It is encrypted with `MASTER_ENCRYPTION_KEY` (AES-256-GCM) and never returned from APIs.
3. Optional dev shortcut: set `COHERE_API_KEY` in `.env`; when present it overrides the DB-stored workspace key for pipeline runtime (local convenience). **Test Cohere** in Settings uses the **saved** workspace key so you verify what is stored for production.

Default models are seeded in workspace `pipeline_settings`: `command-r7b-12-2024` (small), `command-a-plus-05-2026` (large), `embed-v4.0`, `rerank-v4.0-fast`. **`EMBEDDING_DIM`** defaults to **1536** for embed v4 (override if you truncate vectors / rebuild indexes).

### Graphiti concurrency

Graphiti uses a semaphore for concurrent LLM/graph work. Tune **`SEMAPHORE_LIMIT`** (integer) if you hit provider rate limits or want lower parallelism; see upstream Graphiti docs.

## Repository layout

| Path | Purpose |
| ---- | ------- |
| [specs/](specs/) | Product and technical specifications |
| [sprints/](sprints/) | Sprint plans and task checklists |
| [apps/web/](apps/web/) | Next.js 14 web UI |
| [apps/pipeline/](apps/pipeline/) | FastAPI pipeline service |
| [apps/migrations/](apps/migrations/) | Alembic migrations (Compose one-shot `migrate`) |

### Specifications

- [specs/prd.md](specs/prd.md) — Product requirements  
- [specs/personas.md](specs/personas.md) — User personas  
- [specs/userstories.md](specs/userstories.md) — Epics and user stories  
- [specs/datamodel.md](specs/datamodel.md) — Working-store entities, ERD  
- [specs/techstack.md](specs/techstack.md) — Stack choices  
- [specs/apis.md](specs/apis.md) — HTTP contracts  
- [specs/uiux.md](specs/uiux.md) — IA, design tokens, accessibility  

### Sprints

- [sprints/sprintplan.md](sprints/sprintplan.md) — Master plan  
- [sprints/sprint_1/sprint_1_tasks.md](sprints/sprint_1/sprint_1_tasks.md) — Sprint 1 checklist  

## Prerequisites

- **Docker Desktop** or Docker Engine + Compose v2  
- **pnpm 9.x** and **Node 22+** (for local web dev / `pnpm build`; the Compose `web` image uses Node 22)  
- **Python 3.12** (for local pipeline dev — optional if you only use Compose)

## Quick start (Docker Compose)

1. Copy env template and **fill secrets** (values must be non-empty where noted):

   ```bash
   cp .env.example .env
   ```

   Generate keys:

   ```bash
   openssl rand -base64 32   # MASTER_ENCRYPTION_KEY
   openssl rand -hex 32      # INTERNAL_PIPELINE_TOKEN (opaque shared secret)
   ```

   **URLs:** `docker-compose.yml` overrides `DATABASE_URL`, `REDIS_URL`, FalkorDB host/port, and `PIPELINE_INTERNAL_URL` for services inside the Compose network. Your `.env` can use `localhost` for host-side tools (`pnpm dev`, Alembic on the host); Compose still connects to `postgres`, `redis`, and `falkordb` containers.

2. Start the stack (builds images, runs migrations once, then pipeline + web):

   ```bash
   docker compose up --build
   ```

3. Open the UI: **http://localhost:3000** (redirects to `/documents`). Core routes: Documents (PDF upload + status), Notes, Graph, Chat, Snapshots, External Targets, Settings.

When Next runs via **`pnpm dev`** on the host, keep **`PIPELINE_INTERNAL_URL=http://127.0.0.1:8000`** and ensure the **pipeline** container publishes **8000** (see `docker-compose.yml`). After adding or changing `ports:` for pipeline, recreate it so the bind appears: **`docker compose up -d pipeline --force-recreate`**.

### PDF upload (storage)

- **`MAX_UPLOAD_BYTES`** — upper bound per uploaded PDF (default **52428800**, i.e. 50 MiB). Set in `.env` for pipeline + web.
- **`ZKAST_STORAGE_ROOT`** — directory where PDF bytes are written (default **`/var/zkast/storage`** in Compose). The **`pipeline`** and **`worker`** services mount the named volume **`pipeline_storage`** at this path so parsing can read what the API wrote.
- **`worker`** runs **`arq app.tasks.WorkerSettings`** (Arq) against **`REDIS_URL`**; keep it running alongside **`pipeline`** for ingest jobs to complete.
- To delete stored PDFs only, remove the Docker volume **`zkast_pipeline_storage`** (exact name depends on project prefix) or run **`docker compose down -v`** (this also deletes Postgres **`pgdata`**).

4. Smoke-check aggregated readiness from the web tier:

   ```bash
   curl -s http://localhost:3000/api/v1/readyz | jq .
   ```

   Expect `status: "ok"` when Postgres, Redis, FalkorDB, and pipeline checks are healthy.

### Dev builds (without Docker)

```bash
pnpm install
pnpm run build          # Next.js production build (web package)
```

Pipeline tests — from the repo root (creates `apps/pipeline/.venv` if missing):

```bash
pnpm run test:pipeline
```

Or manually:

```bash
cd apps/pipeline
python3 -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export MASTER_ENCRYPTION_KEY="$(openssl rand -base64 32)"
python -m pytest
```

Optional live Graphiti + Cohere + FalkorDB smoke (Compose **up**, real `COHERE_API_KEY`, host ports published by `docker-compose.yml`: Postgres **5432**, Redis **6379**, FalkorDB **6380→6379**):

```bash
export ZKAST_GRAPHITI_SMOKE=1
export COHERE_API_KEY="..."
export DATABASE_URL=postgresql://zkast:zkast@localhost:5432/zkast
export INTERNAL_PIPELINE_TOKEN=...
export MASTER_ENCRYPTION_KEY=...
export REDIS_URL=redis://localhost:6379/0
export FALKORDB_HOST=localhost
export FALKORDB_PORT=6380
cd apps/pipeline && python -m pytest tests/test_graphiti_smoke.py -q
```

Optional ingestion parse smoke (Compose **up**, migration **0004** applied, same defaults as Graphiti smoke for DB/Redis/token):

```bash
export ZKAST_INGESTION_SMOKE=1
export DATABASE_URL=postgresql://zkast:zkast@localhost:5432/zkast
export INTERNAL_PIPELINE_TOKEN=...
export MASTER_ENCRYPTION_KEY=...
export REDIS_URL=redis://localhost:6379/0
export ZKAST_STORAGE_ROOT=/tmp/zkast-ingest-test
cd apps/pipeline && python -m pytest tests/test_ingestion_worker.py -q
```

## Security note (**FR-33**, **NFR-11**)

Sprint 1 ships **bypass authentication** for a **single local operator**. It is **not** safe to expose this configuration to the public internet. Treat Compose + `.env` as **trusted LAN / single-user dev only** until real auth ships in later sprints.

## Vision

- Turn unstructured PDFs into **atomic notes** with provenance (document + pages).
- Maintain a **working graph** you can explore and edit before persistence.
- **Grounded chat** with inline citations.
- **Optional persistence** to **Neo4j 5.26+** or **Postgres + AGE**.

## License

Not specified in this repository yet. Add a `LICENSE` file when you choose one for the project.

## Acknowledgments

- Knowledge graph engine: [Graphiti](https://github.com/getzep/graphiti) (Zep / Apache-2.0).
