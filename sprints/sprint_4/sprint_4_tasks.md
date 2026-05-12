# Sprint 4 — Atomic Notes and Graph Extraction

**Status**: **Closed** (2026-05-12) — see [sprint_4_report.md](sprint_4_report.md).

**Duration**: 2 weeks  
**Goal**: Run **Zettelkasten** atomic-note generation and **Graphiti** entity/relationship extraction from Episodes; persist **`AtomicNote`**, **`NoteLink`**, **`Entity`**, **`Relationship`** with provenance; Notes UI (list + detail + autosave); manual note + manual links; **re-ingest** and **document delete** with cascade options. **FR-5–FR-15**, **US-1.4–US-1.5**, **US-2.1–US-2.6**.

## Inputs

- Parsed Episodes from Sprint 3.
- Graphiti + Cohere from Sprint 2.

## Outputs

- After ingestion completes: populated Notes panel + graph API returns nodes/edges (may still be raw Graphiti-shaped internally — normalize to datamodel IDs).
- User can edit notes, merge/split (UI hooks minimal acceptable if merge/split deferred to Sprint 5 — prefer completing **US-2.3–US-2.4** here if time).

## Dependencies

- **Sprint 3** complete.

---

## Web tier

- [x] Notes list: search, filters tags/document/origin (**apis.md** GET `/notes`).
- [x] Note detail: title/body/tags editor, markdown preview, autosave indicator (**US-2.2**).
- [x] Create manual note (**US-2.5**); distinguish badge (**US-2.5** AC-3).
- [x] Note linking UI: add/remove links (**US-2.6**).
- [x] Document detail: ingestion runs timeline + retry from stage (**US-7.1** partial — retry entry).
- [x] Re-ingest flow UI: `replaces_document_id` (**US-1.4**, **FR-5**).
- [x] Delete document modal with cascade preview (**US-1.5**, **FR-6**).

## Pipeline service

- [x] Stage pipeline after parsing: `generating_notes` → `extracting_graph` → `building_graph` → `ready` (**FR-2**, align **Document.status** enum with [datamodel.md](../../specs/datamodel.md)).
- [x] Prompt templates for atomic notes: one idea per note, citation to episodes/pages (**FR-7–FR-8**).
- [x] Feed episodes / generated notes into Graphiti for entity & relationship extraction (**FR-12–FR-14**).
- [x] **Dedup** entities `(workspace_id, type, canonical_name)` (**FR-15**, **datamodel.md** constraints).
- [x] Persist relational projection: map Graphiti internal IDs ↔ zkast `Entity`/`Relationship` UUIDs (adapter layer).
- [x] Re-ingest creates new `IngestionRun` + Episodes; does not hard-delete prior graph (**FR-5**).

## Data + migrations

- [x] Tables: `atomic_notes`, `note_links`, `entities`, `relationships`, junctions for provenance arrays as needed (normalized `note_episodes`, etc.).
- [x] FK integrity for cascade delete paths (**FR-6**).

## Infra + Docker

- [x] Tune `SEMAPHORE_LIMIT` for Cohere (**techstack.md** Graphiti note).

## Design + UX

- [x] Note typography: Crimson Pro `body-lg`, max-width 68ch (**uiux.md**).

## Docs

- [x] Prompt tuning knobs in workspace settings (defer UI to Sprint 8 if only env-based here).

---

## Definition of Done

- [x] Single PDF produces multiple atomic notes with `source_episode_ids` (**FR-8**).
- [x] Graph contains ≥1 entity and ≥1 relationship for fixture PDF.
- [x] Manual note participates in extraction on next incremental job OR explicit "re-extract" action documented.

## Risks and mitigations

| Risk | Mitigation |
| ---- | ---------- |
| Graphiti ↔ zkast ID mapping bugs | Golden-file integration test on tiny PDF |
| Note quality variance | Allow max-notes-per-doc cap (**FR-8** AC-4) |

## Out of scope

- Force-directed graph canvas (**Sprint 5**).
- Snapshots (**Sprint 5**).

---

## Sprint review (final)

### Demo readiness

- Documents: full panel with SSE when a **job_id** is known, **4s polling** while any row is mid-ingestion, detail drawer with ingestion runs, retry from **parsing / notes / graph**, re-ingest upload, cascade delete preview + options.
- Notes: list with search/origin/document filters, detail with debounced autosave, manual badge, links, merge dialog (other note UUID + per-field pickers), split from textarea selection.
- Pipeline: **`0005_notes_graph`** migration, worker stages, internal notes + ingestion + delete APIs documented in **`specs/apis.md`**.

### Verification (closeout — 2026-05-12)

- **`pnpm run build`** (repo root): passed.
- **`pnpm run test:pipeline`**: **10 passed**, **5 skipped** (DB / Graphiti integration tests skip without migrated `DATABASE_URL` and gates).

### Closeout engineering notes

- **Arq worker**: **`worker_startup`** creates **`ctx["arq_pool"]`** so **`parse_document` / `generate_atomic_notes`** can **`enqueue_job`** the next stage (fixes **`KeyError: 'arq_pool'`** and UI **`failed`** rows with that substring).
- **Ingestion retry**: removed blanket **`is_document_ingestion_active`** block for **parsing**; **`fail_running_ingestion_runs_for_document`** before **notes/graph** retries; **Notes** retry no longer 409s solely because the run is **`running`**.
- **Status ordering**: enqueue **next** Arq job **before** flipping document DB status to **`generating_notes` / `extracting_graph`** to avoid “stuck” states if enqueue fails.
- **GET note detail**: serialize **`note_links.created_at`** (ISO strings) so **`JSONResponse`** does not 500 on **`datetime`** (**fixes invalid JSON / “Internal S…”** in the Notes UI).
- **Documents UI**: prune orphan progress; **`listRefreshNonce`** keeps detail drawer aligned with polled list; **`messageFromApiJson`** for delete/retry errors (**FastAPI `detail`**).
- **Parse errors**: explicit **PDF missing on volume** message when file absent vs shared **`ZKAST_STORAGE_ROOT`**.
- **Graphiti concurrency**: default **`max_coroutines=10`** when **`SEMAPHORE_LIMIT`** unset; Compose sets **`SEMAPHORE_LIMIT=10`** on **pipeline** and **worker** ([**techstack.md**](../../specs/techstack.md)).

### Gaps / issues (carry forward)

- **SEMAPHORE_LIMIT**: tuned default **10**; operators with higher Cohere quotas may raise via env (see **techstack.md**).
- Graphiti retry may re-emit duplicate episodes in Falkor for the same logical content; maps keep Postgres canonical.
- Integration pytest modules require **Alembic through `0005_notes_graph`** on **`DATABASE_URL`** or they skip.
- FastAPI **`HTTPException`** **`detail`** vs uniform **`{ error: ... }`** — normalized in **document detail** / **note load** where we touched; not global middleware.

### Next sprint prep

- **Sprint 5**: graph visualization (**`react-force-graph`**), snapshots, entity merge polish in UI ([sprintplan.md](../sprintplan.md)).
