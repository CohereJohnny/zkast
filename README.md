# zkast

**zkast** (“zettelkasten + cast”) ingests **PDFs**, generates **atomic Zettelkasten-style notes**, builds an **Obsidian-style knowledge graph** backed by [Graphiti](https://github.com/getzep/graphiti) and [LangExtract](https://github.com/google/langextract) (source-grounded evidence spans), and supports **grounded chat** over your corpus using **Cohere** (with citations). After review, you can **persist** snapshots to a graph database you control—**Neo4j** or **Postgres with Apache AGE**.

The product is **self-hostable first** (Docker Compose, BYO Cohere key) with a path toward multi-user and SaaS later.

## P0 status

| Sprint | Tag | Highlights |
| --- | --- | --- |
| 4 | `sprint-4` | Atomic notes, graph extraction, notes workspace UI |
| 5b | `sprint-5b` | Graph viz, merge with persisted undo, snapshots + review, JobLogConsole drawer, heartbeat reconciler, Diagnostics page |
| 5c | `sprint-5c` | Typed Graphiti extraction (Pydantic taxonomy), LangExtract source-grounded evidence, picklist filter UX |
| 6 | _planned_ | Grounded chat with retrieval + citations (see [sprints/sprint_6/sprint_6_tasks.md](sprints/sprint_6/sprint_6_tasks.md)) |

## Architecture

zkast is a two-process system: **Next.js 14** (UI + public HTTP) and **FastAPI** (Graphiti, LangExtract, ingestion, chat orchestration). Both read the working store in **Postgres**; the pipeline talks to **FalkorDB** for the working graph and **Cohere** (Command via OpenAI-compat, `embed-v4.0`, `rerank-v4.0-fast`) for all LLM operations in P0.

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

Graphiti bounds concurrent LLM, embedding, and rerank calls (`max_coroutines`). zkast **`build_graphiti`** uses **`SEMAPHORE_LIMIT`** when set; otherwise it defaults to **10** (Cohere-friendly for `extract_graph` bursts). Docker Compose sets **`SEMAPHORE_LIMIT=10`** on **pipeline** and **worker**. Raise toward **16–20** if your Cohere quota allows; lower to **4–6** if you still see **429** throttling. Upstream `graphiti-core` also reads this env at import (default **20** there); zkast’s explicit `max_coroutines` wins for instances we construct.

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

- [sprints/sprintplan.md](sprints/sprintplan.md) — Master plan (P0/P1 sprint dependency graph)
- [sprints/bug_swatting.md](sprints/bug_swatting.md) — Bug log (BUG-001 onward)
- [sprints/tech_debt.md](sprints/tech_debt.md) — Technical debt log (TD-001 onward)
- [sprints/sprint_6/sprint_6_tasks.md](sprints/sprint_6/sprint_6_tasks.md) — **Next up**: Grounded chat

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

### Ingestion observability (Sprint 5b)

- **Pipeline log drawer**: a collapsible bottom panel on every workspace
  route streams live worker events (parse / notes / graph stages, per-episode
  progress, Cohere token counts) via SSE. Closed by default; click the
  console tab to expand. The drawer subscribes to all active ingestion jobs
  registered by the documents panel.
- **Heartbeats + reconciler**: each pipeline task writes
  `ingestion_runs.last_heartbeat_at` every 10 seconds. A worker cron
  (`reconcile_stuck_documents`) sweeps once a minute and flips any document
  still in an active status whose heartbeat is older than 90 s to **failed**
  with `failure_reason='worker_crashed_during_<stage>'` — so a hard worker
  kill no longer leaves zombies in the UI.
- **`CancelledError` handling**: a `docker compose restart worker` mid-flight
  now flips the document to `failed:cancelled_by_worker_shutdown` cleanly
  (Python 3.8+ makes `CancelledError` a `BaseException`; the worker explicitly
  catches it).
- **Streaming notes synthesis**: `notes_llm` now calls Cohere with
  `stream=True`, `timeout=120 s`, `max_retries=1`. Per-50-token progress
  bumps appear in the log drawer. Disable with
  `pipeline_settings.notes_llm_streaming = false` if a model misbehaves.
- **Parallel graph extraction**: `extract_graph` processes episodes via
  `asyncio.gather` with a configurable semaphore
  (`pipeline_settings.graph_extract_concurrency`, default 4, max 8). Expect
  ~3–4× wall-time speedup on a 19-page PDF vs Sprint 5.
- **Diagnostics page**: **Settings → Diagnostics** (`/settings/diagnostics`)
  shows arq queue depth + in-progress, stalled documents, per-stage P50/P95
  for the last 24 h, and a safe **Clean terminal job hashes** action that
  only deletes Redis hashes whose status is succeeded / failed / cancelled.

### Merge undo (Sprint 5b)

Both entity and note merge dialogs now offer two roll-back paths after a
successful merge:

- **Full undo** — restores the deleted victim row and re-attaches its
  provenance from `merge_audit_log`. Calls `POST .../entities/{id}/unmerge`
  or `POST .../notes/{id}/unmerge`.
- **Revert survivor fields** — keeps the merge but PATCHes the survivor's
  field values back to their pre-merge state. Faster, narrower.

### Typed extraction, source evidence, filter pickers (Sprint 5c)

- **Typed Graphiti extraction**: `apps/pipeline/app/entity_schemas.py` ships
  10 Pydantic entity models (`Person`, `Organization`, `Location`,
  `Document`, `Standard`, `Equipment`, `Process`, `Material`, `Event`,
  `Concept`) and 8 typed edge models. `graphiti.add_episode(...)` receives
  these via `entity_types=` / `edge_types=` / `edge_type_map=` so the graph
  legend no longer collapses to 100% `Concept`. Every model carries at
  least one required field so Pydantic-emitted JSON schemas satisfy
  Cohere's `response_format` validator (BUG-010).
- **LangExtract source evidence**: a co-extractor runs alongside Graphiti
  per episode, returning character-offset spans. Matches are persisted to
  `entity_evidence` (Alembic `0008_entity_evidence`) and surfaced as a
  **Evidence** section in the entity detail panel: per-entity blockquotes
  with a "View in document" link to the source PDF page.
- **Graph filter pickers**: every UUID/CSV input in the graph filter bar
  is replaced by a searchable picklist backed by real data —
  `DocumentPicker` (combobox over ready documents),
  `EntityTypeahead` (debounced typeahead + chip-based multi-select),
  `TypeMultiselect` (entity + edge type chip groups with counts),
  `TagPicker` (combobox over distinct atomic-note tags). Query-string
  contract is preserved.

### Graph view & snapshots (Sprint 5)

- **Graph** (`/graph` and workspace right rail): loads the working graph from **`GET /api/v1/workspaces/{id}/graph`** with URL-synced filters (`view`, `document_id`, `tag`, `entity_type`, `edge_type`, `valid_at`, `node_limit`, `depth`, `seed_entity_ids`). Large workspaces may return **`truncated: true`** — narrow filters or raise `node_limit` (max **25000**).
- **Canvas**: Sigma + graphology; **ForceAtlas2** runs in a **Web Worker** for a few seconds, then the layout is imported into Sigma. Use **Accessible list** (or automatic fallback on canvas error / reduced motion) for a keyboard-friendly entity list.
- **Editing**: selection panel supports **merge** (with optional **revert survivor fields** after merge), **manual edges** (create / PATCH / end via `DELETE` on the relationship route), and provenance links to notes.
- **Snapshots** (`/snapshots`): **`POST …/snapshots`** freezes entities, relationships, and notes under **`graph_snapshots`** (Alembic `0006_graph_snapshots`). Empty workspaces return **`business_rule_violation`**. Sprint 5b added a three-state **review workflow** (`approved` / `rejected` / `needs_changes`) via **`POST …/snapshots/{id}/review`** stored in `snapshot_reviews` (Alembic `0007_ingestion_observability`).

When Next runs via **`pnpm dev`** on the host, keep **`PIPELINE_INTERNAL_URL=http://127.0.0.1:8000`** and ensure the **pipeline** container publishes **8000** (see `docker-compose.yml`). After adding or changing `ports:` for pipeline, recreate it so the bind appears: **`docker compose up -d pipeline --force-recreate`**.

### PDF upload (storage)

- **`MAX_UPLOAD_BYTES`** — upper bound per uploaded PDF (default **52428800**, i.e. 50 MiB). Set in `.env` for pipeline + web.
- **`ZKAST_STORAGE_ROOT`** — directory where PDF bytes are written (default **`/var/zkast/storage`** in Compose). The **`pipeline`** and **`worker`** services mount the named volume **`pipeline_storage`** at this path so parsing can read what the API wrote.
- **`worker`** runs **`arq app.tasks.WorkerSettings`** (Arq) against **`REDIS_URL`**; keep it running alongside **`pipeline`** for ingest jobs to complete.
- **Ingestion stages (Sprint 4)** — after PDF parse, the worker chains: **`generating_notes`** (Cohere → `atomic_notes` + optional `note_links`) → **`extracting_graph`** / **`building_graph`** (Graphiti `add_episode` with `group_id = workspace_id` → Postgres `entities` / `relationships` + Graphiti UUID maps) → **`ready`**. Tune note volume with workspace **`pipeline_settings.max_notes_per_document`** (default **50**, capped at 500 in the worker).
- **Re-ingest** — upload a PDF via `POST /api/v1/workspaces/{id}/documents` with multipart field **`replaces_document_id`** set to an existing document UUID. The new document gets its own `IngestionRun` and episodes; prior documents’ notes and graph rows are **not** removed automatically (see FR-5).
- **Document delete** — `DELETE .../documents/{id}?cascade=document_only` removes the document row (Postgres cascades episodes/runs). `cascade=exclusive_derivatives` first deletes notes that are **only** tied to that document’s episodes, then removes orphan entities/relationships that have no remaining episode or note provenance, then deletes the document. **`GET .../documents/{id}/delete-preview`** returns counts for the modal. Deletes and ingestion retries return **`409`** with `error.code: business_rule_violation` while the document is mid-pipeline (`queued`, `parsing`, `generating_notes`, `extracting_graph`, `building_graph`) or has an ingestion run still **`running`**.
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

Optional ingestion parse smoke (Compose **up**; the smoke itself requires migration **0004** at minimum, but the Compose stack expects the full chain through **0008_entity_evidence**; same defaults as Graphiti smoke for DB/Redis/token):

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
