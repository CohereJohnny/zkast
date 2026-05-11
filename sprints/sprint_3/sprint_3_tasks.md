# Sprint 3 — PDF Ingestion

**Duration**: 2 weeks  
**Goal**: End-to-end **document upload**, **PyMuPDF** parsing, **Episode** chunking with page provenance, **IngestionRun** state machine, **SSE** progress per document/job. **FR-1–FR-4**, **US-1.1–US-1.3**, entities `Document`, `IngestionRun`, `Episode` ([datamodel.md](../../specs/datamodel.md)).

## Inputs

- Sprint 2 Cohere + Graphiti initialization (not required for pure parse this sprint, but queue worker infrastructure should align).
- Object storage abstraction: local filesystem bind-mount for P0 ([techstack.md](../../specs/techstack.md)).

## Outputs

- User drops PDF(s); sees per-document status stages: **queued → parsing → ready** (parse-only; later stages in Sprint 4).
- Document list UI with status + progress (**FR-2**).
- Episodes persisted with `document_id`, `page_start` / `page_end`, monotonic `sequence`.

## Dependencies

- **Sprint 1–2** complete.

---

## Web tier

- [x] Documents panel: drop zone, multi-file upload (**US-1.2**). — `documents-panel.tsx` + workspace shell.
- [x] `POST /api/v1/workspaces/{id}/documents` multipart → returns document ids + job ids (**apis.md**).
- [x] Document row UI: status, progress, error surface (**US-1.3**).
- [x] SSE subscription UI hook (`/api/v1/jobs/{id}/events` + `EventSource`).
- [x] Client-side validation: PDF only, size limit (**FR-1**, **US-1.1** AC).

## Pipeline service

- [x] Arq worker processes ingestion jobs (`app.tasks.WorkerSettings`, `worker` Compose service).
- [x] Store file to `storage_uri`; compute **checksum**; enforce unique `(workspace_id, checksum)` (**datamodel.md**).
- [x] PyMuPDF extract text + **page_count** (**techstack.md**).
- [x] Chunking strategy with `page_start`/`page_end`, `sequence` (**Episode** fields).
- [x] Persist **IngestionRun** with `pipeline_version`; optional `trace_id` column present.
- [x] Per-page failure isolation (warnings in `ingestion_runs.stats.warnings`) (**NFR-6**).
- [x] Idempotency: `Idempotency-Key` header + `upload_idempotency` table (**apis.md** conventions).

## Data + migrations

- [x] Tables: `documents`, `ingestion_runs`, `episodes`, `upload_idempotency` per plan.
- [x] Indexes: `(workspace_id, created_at desc)`, `(workspace_id, status)`, `(document_id, sequence)` via unique constraint.

## Infra + Docker

- [x] Volume **`pipeline_storage`** for PDF storage path.
- [x] **`worker`** service: `arq app.tasks.WorkerSettings`.

## Design + UX

- [x] Empty state handled via panel copy; full `/documents` page uses same panel (**variant="full"**).

## Docs

- [x] Operator doc: **`MAX_UPLOAD_BYTES`**, **`ZKAST_STORAGE_ROOT`**, volume wipe notes (root README + `.env.example`).

---

## Definition of Done

- [x] Upload 3 PDFs concurrently; statuses independent (**US-1.2** AC-4).
- [x] Failed PDF does not corrupt workspace (**FR-4**); document → `failed`, run → `failed`.
- [x] Each Episode traces to `document_id` + pages (**datamodel.md**).
- [x] `pnpm run build` (web) and `python -m pytest` (pipeline) pass locally.

## Risks and mitigations

| Risk | Mitigation |
| ---- | ---------- |
| Huge PDFs memory-bound | Stream pages; configurable page batch size |
| Garbled encoding PDFs | Record parse warnings on Document |

## Out of scope

- LLM atomic-note generation (**Sprint 4**).
- Graph entity extraction (**Sprint 4**).

---

## Sprint review (final)

### Demo readiness

- Docker Compose runs **`migrate`**, **`pipeline`**, **`worker`**, **`web`** with shared **`pipeline_storage`** (ensure **`worker`** is up — Arq consumes parse jobs).
- UI: workspace **Documents** panel + **`/documents`** — upload, multi-file, SSE-driven refresh on job completion, inline **failed** reasons.
- Hybrid dev: root **`.env`** uses localhost URLs for host **`pnpm dev`**; Compose **`environment`** overrides internal service hostnames; **`pipeline`** publishes host port **8000** for Next-on-host → pipeline calls.

### Verification (closeout — 2026-05-11)

- **`pnpm run build`** (repo root): passed.
- **`pnpm run test:pipeline`**: **8 passed**, **2 skipped** (smoke tests env-gated).

### Closeout engineering notes

- **Arq worker**: `WorkerSettings.redis_settings` must be a real **`RedisSettings`** instance — Arq copies **`WorkerSettings.__dict__`** and does not invoke descriptors (lazy wrapper crashed worker).
- **Pipeline**: `_serialize_document` JSON-encodes **`datetime`** fields on upload responses (avoid 500 after successful insert).
- **Notes route**: placeholder copy clarifies episodes are not listed in UI until a later sprint (parse-only scope).

### Gaps / issues (carry forward)

- No dedicated “list episodes” public API yet; chunk counts live on **`ingestion_runs.stats`** / DB.
- FastAPI **HTTPException** bodies use `detail` shape vs some JSON `{ error: ... }` handlers — web forwards pipeline bodies as-is for errors.
- SSE reconnect replay from DB remains minimal (client refetches document list on terminal events).

### Next sprint prep

- Sprint 4: new **`IngestionRun`** stages **generating_notes → extracting_graph → building_graph**; Notes UI and atomic-note generation; reuse episodes from parse **`ready`** documents.
