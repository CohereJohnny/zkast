# Sprint 4 report — Atomic notes and graph extraction

**Goal**: **Zettelkasten** atomic-note generation, **Graphiti** entity/relationship extraction, relational projection with provenance, **Notes** UI (list, detail, autosave, links, merge/split), document **re-ingest** and **cascade delete** — **FR-5–FR-15**, **US-1.4–US-1.5**, **US-2.1–US-2.6** ([sprint_4_tasks.md](sprint_4_tasks.md)).

**Status**: **Complete** — task checklist and Definition of Done satisfied; closeout verification **2026-05-12**: **`pnpm run build`** OK; **`pnpm run test:pipeline`** OK (**10 passed**, **5 skipped** — DB-heavy modules skip without migrated `DATABASE_URL`).

## Completed

- **Migrations**: Alembic **`0005_notes_graph`** — `atomic_notes`, `note_episodes`, `note_links`, `entities`, `entity_episodes`, `entity_notes`, `relationships`, `relationship_episodes`, `relationship_notes`, `graphiti_entity_map`, `graphiti_edge_map`, indexes and uniques per [datamodel.md](../../specs/datamodel.md).
- **Pipeline**: `notes_repo`, `entities_repo`, `relationships_repo`, `graphiti_mapper`, `cascade`, `notes_llm`; **`parse_document` → `generate_atomic_notes` → `extract_graph`** Arq chain; document statuses **`generating_notes`**, **`extracting_graph`**, **`building_graph`**, **`ready`**; internal notes CRUD/merge/split/links; document delete-preview + cascade **`exclusive_derivatives`**; **`POST /internal/v1/ingestion-runs`** with **`from_stage`**; **`worker_startup`** exposes **`arq_pool`** for chained **`enqueue_job`** calls.
- **Web**: API routes for notes, document detail (ingestion runs, retry, re-ingest, delete), delete-preview; **`documents-panel`** (list polling while ingestion active, SSE when job known); **`document-detail-panel`** (FastAPI **`detail`** error parsing); **`note-detail`** (safe JSON load); Notes page list + detail UX (**uiux.md** typography).
- **Infra / ops**: **`SEMAPHORE_LIMIT=10`** in Compose + **`graphiti_factory`** default for Cohere-friendly Graphiti concurrency ([techstack.md](../../specs/techstack.md)); **`docker compose run --rm migrate`** / migrate-on-`up` workflow unchanged.
- **Tests**: `test_notes_repo`, `test_notes_generation`, `test_entities_dedup`, `test_graphiti_mapper`, `test_cascade`, optional **`ZKAST_INGESTION_SMOKE`** **`test_ingestion_worker`** with mocked **`arq_pool`**.
- **Docs**: Root **README** (stages, `max_notes_per_document`, cascade, semaphore), **`specs/apis.md`**, **`apps/pipeline/README.md`**.

## Demo readiness

- **`docker compose up -d --build`**: **`migrate`** through **`0005`**, **`pipeline`** + **`worker`** + **`web`** healthy; shared **`pipeline_storage`** for PDFs.
- **Documents**: upload, multi-stage statuses, detail drawer with runs + **retry (parsing / notes / graph)** + re-ingest + cascade delete modal.
- **Notes**: filters, detail with autosave, manual badge, links, merge/split flows against pipeline.

## Gaps / follow-ups

- **Graph canvas**: placeholder only until **Sprint 5** (force-directed viz).
- **Graphiti / Falkor**: retries may duplicate logical episodes in the working graph; Postgres maps and relational **`Entity`/`Relationship`** rows remain canonical.
- **HTTP error shape**: some pipeline paths still return FastAPI **`detail`** wrappers; web normalizes in critical panels, not everywhere.
- **Integration pytest**: full green needs **`DATABASE_URL`** + Alembic through **`0005`** (otherwise skips).

## Next sprint prep

- **Sprint 5**: **`react-force-graph`** canvas, snapshots, richer merge/split UX, graph filters and provenance drill-down ([sprintplan.md](../sprintplan.md)).
