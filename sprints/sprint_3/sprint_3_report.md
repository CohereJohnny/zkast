# Sprint 3 report — PDF ingestion (parse stage)

**Goal**: End-to-end **PDF upload**, **PyMuPDF** parsing, **Episode** chunking with page provenance, **IngestionRun** tracking, **SSE** job progress — **FR-1–FR-4**, **US-1.1–US-1.3** ([sprint_3_tasks.md](sprint_3_tasks.md)).

**Status**: **Complete** — task checklist and Definition of Done satisfied; closeout verification: **`pnpm run build`** OK; **`pnpm run test:pipeline`** OK (8 passed, 2 skipped).

## Completed

- **Migrations**: Alembic **`0004_documents_ingestion`** — `documents`, `ingestion_runs`, `episodes`, `upload_idempotency`; indexes and **`(workspace_id, checksum)`** uniqueness.
- **Pipeline**: `LocalStorage`, `documents_repo`, `chunking`, **`parse_document`** Arq task (per-page warning isolation), internal **`POST /internal/v1/documents`**, **`DELETE`**, **`POST /internal/v1/ingestion-runs`**, job poll + Redis pub/sub events for SSE; **`_serialize_document`** emits JSON-safe rows (datetime → ISO strings).
- **Worker**: Compose **`worker`** service (`arq app.tasks.WorkerSettings`); **`redis_settings`** from **`REDIS_URL`** env as concrete **`RedisSettings`** (Arq-compatible).
- **Web**: Documents API routes (list, upload, delete), jobs + **EventSource** proxy routes; **`documents-panel.tsx`** (drop zone, validation, progress); **`/documents`** full variant; workspace grid hides duplicate Documents panel on **`/documents`**; root **`.env`** loaded via **`next.config.mjs`** for local dev; upload returns **503** with clear copy when pipeline **`fetch`** fails.
- **Compose / ops**: **`pipeline_storage`** volume; **`DATABASE_URL` / `REDIS_URL` / FalkorDB / `PIPELINE_INTERNAL_URL`** overrides for in-network services; **`pipeline`** publishes **`8000:8000`** for hybrid dev; **`.env.example`** defaults oriented to localhost + README notes.
- **Tests**: **`test_chunking.py`**, **`test_storage.py`**; optional **`ZKAST_INGESTION_SMOKE=1`** **`test_ingestion_worker.py`**.
- **Docs**: Root README (PDF storage, hybrid URLs, worker), **`apps/pipeline/README`**, **`specs/apis.md`** internal ingest contract.

## Demo readiness

- **`docker compose up -d`** (or **`up --build`**): **`migrate`** completes, **`pipeline`** healthy, **`worker`** running, **`web`** on **3000**.
- Upload PDF(s) from UI; statuses **queued → parsing → ready** (or **failed** with reason); concurrent uploads behave independently.

## Gaps / follow-ups

- Episodes persisted in Postgres; **no public list-episodes API** or Notes browser yet (**Sprint 4**).
- Pipeline **`HTTPException`** **`detail`** shape vs uniform **`{ error: ... }`** — web forwards bodies as-is on some paths.
- Minimal SSE replay; no ingest rate limits (**P0 unlimited** per spec).

## Next sprint prep

- **Sprint 4**: Atomic notes, entity/relationship extraction, graph build stages, **`IngestionRun`** beyond parse; surface episodes in Notes UI; optional **`graphiti_for_workspace`** integration from parse output ([sprintplan.md](../sprintplan.md)).
