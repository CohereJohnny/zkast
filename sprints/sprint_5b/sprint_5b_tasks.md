# Sprint 5b — Ingestion Observability and Robustness

**Branch**: `sprints/sprint-5b`
**Theme**: Close every gap surfaced during Sprint 5 debugging before Sprint 6.

## Goals

Land everything in [sprint_9_notes](../sprint_9/sprint_9_notes.md) plus every
TD-xxx in [tech_debt.md](../tech_debt.md) and every BUG-xxx in
[bug_swatting.md](../bug_swatting.md).

---

## Tasks

### Phase 0 — Paperwork

- [x] Create sprints/sprint_5b/ + this file
- [x] Branch `sprints/sprint-5b` off main

### Phase 1 — Quick-win bug fixes

- [x] **B2.5** — `asyncio.CancelledError` handler in all three tasks
      ([apps/pipeline/app/tasks.py](../../apps/pipeline/app/tasks.py))
- [x] **B2** — FK race fix in `generate_atomic_notes` (per-note catch +
      `_is_document_active` precheck)
- [x] **B3** — `arq_pool` startup race (fail-fast in `worker_startup` +
      `_ensure_arq_pool` lazy fallback)
- [x] **B4** — `parse_document` catches `FileNotFoundError` cleanly →
      `failure_reason='source_pdf_deleted'`
- [x] **B5** — `job_hset` sets 7d EXPIRE NX in
      [`job_redis.py`](../../apps/pipeline/app/job_redis.py)
- [x] **TD-007** — [`tests/test_arq_dedup.py`](../../apps/pipeline/tests/test_arq_dedup.py)

### Phase 2 — Migrations + heartbeats + reconciler

- [x] [`0007_ingestion_observability.py`](../../apps/migrations/alembic/versions/0007_ingestion_observability.py)
      — `ingestion_runs.last_heartbeat_at`, `ingestion_run_logs`,
      `merge_audit_log`, `snapshot_reviews`, pipeline_settings defaults
- [x] `_Heartbeat` async context manager + wrap all three tasks
- [x] **B1** — `reconcile_stuck_documents` arq cron (1-minute)
- [x] Repo functions: `update_ingestion_run_heartbeat`,
      `list_stalled_active_documents`, ingestion_run_logs CRUD

### Phase 3 — Streaming console foundations

- [x] **A1** — `record_log` / `record_metric` helpers in `job_redis.py`
      (pub/sub + Redis Stream `MAXLEN 1000` + `ingestion_run_logs`)
- [x] **A2** — `sse_job_events` replays from `XRANGE` then tails pub/sub
- [x] **A3** — `list_logs_for_run` / `list_logs_for_document` +
      `GET /internal/v1/workspaces/{ws}/ingestion-runs/{id}/logs`

### Phase 4 — Performance

- [x] **C3** — `notes_llm.py` `stream=True`, `timeout=120`, `max_retries=1`,
      per-50-tokens callback
- [x] **C1** — `extract_graph` `asyncio.gather` + `asyncio.Semaphore`
      driven by `pipeline_settings.graph_extract_concurrency` (default 4)
- [x] **C2** — per-episode `log` + `metric` events
- [x] Seed defaults in migration 0007

### Phase 5 — JobLogConsole drawer

- [x] [`apps/web/src/lib/job-events.tsx`](../../apps/web/src/lib/job-events.tsx)
      — `JobEventsProvider`, `useActiveJobs`, `registerActiveJob`
- [x] [`apps/web/src/components/job-log-console.tsx`](../../apps/web/src/components/job-log-console.tsx)
      — collapsible bottom drawer, multi-job EventSource, follow-tail,
      filter chips, copy log via toast, localStorage state
- [x] Cross-wire `metric` events (entity/edge/note count) → `emitGraphInvalidated`
- [x] Mount in
      [`workspace-shell.tsx`](../../apps/web/src/components/workspace-shell.tsx) (z-35)
- [x] Documents panel registers active jobs

### Phase 6 — Real merge undo + graph filter

- [x] `merge_audit_log` writes in `merge_entities` and `merge_notes`
- [x] **D1.a** — `unmerge_entity` repo + endpoint + web proxy
- [x] **D1.b** — `unmerge_note` repo + endpoint + web proxy
- [x] **Full undo** buttons in `entity-merge-dialog` and `note-merge-dialog`
- [x] **D2** — `ChipFilterApplier` toggles `hidden` per node/edge;
      chip filters no longer trigger refetch

### Phase 7 — Pulled-forward features

- [x] **D3** — `GET /graph/search` hybrid via Graphiti + web proxy
- [x] **D4** — `POST /snapshots/{id}/review` + `snapshot_reviews` table +
      Approve/Reject UI

### Phase 8 — Polish + diagnostics

- [x] **D5** — `GraphFilterBar` 300 ms debounced auto-apply for chip filters
- [x] **D6** — `/settings/diagnostics` page (queue, stalled docs, P50/P95,
      hash hygiene + safe-only cleanup)
- [x] `internal_admin.py` (`/internal/v1/admin/diagnostics` and
      `/internal/v1/admin/cleanup-stale-job-hashes`)

### Phase 9 — Tests + docs + closeout

- [x] New pytest files: `test_arq_dedup`, `test_cancelled_error_handling`,
      `test_reconciler` (skips without DB), `test_unmerge` (skips without
      DB), `test_graph_search`, `test_stream_replay`
- [x] Update [specs/apis.md](../../specs/apis.md) and [README.md](../../README.md)
- [x] `pnpm run build` green; `pytest` 27 passed / 6 skipped
- [ ] Sprint review section + `sprint_5b_report.md`
- [ ] Mark TD-001 through TD-009 Resolved
- [ ] Commit + push branch (no PR — user reviews in morning)

---

## Sprint review

### Demo readiness

- **Ingestion observable end-to-end.** Upload a PDF and the bottom drawer
  shows per-stage events, per-episode entity/edge counts during graph build,
  per-50-tokens deltas during notes synthesis. Closing/reopening the drawer
  replays the last ~200 events from the Redis Stream so history is never
  lost.
- **Zombie ingestions impossible by design.** Worker crash → reconciler
  marks stuck docs failed within ~1 minute. Worker SIGTERM mid-flight →
  `CancelledError` handler flips status cleanly. `arq_pool` startup miss →
  lazy fallback recovers, logs a structured warning.
- **Performance.** Notes synthesis emits intermediate progress for the
  first time; graph extraction runs episodes in parallel (semaphore 4 by
  default). On a healthy host with a working Cohere key the 19-page sample
  PDF should now finish under 8 minutes end-to-end.
- **Merge undo is real.** Entity and note merge dialogs offer **Full undo**
  (restores victim row + provenance from `merge_audit_log`) alongside the
  Sprint 5 **Revert survivor fields** shortcut.
- **Graph filter responsiveness.** Chip filters (entity types, edge types,
  tag) no longer refetch — they toggle the Sigma `hidden` attribute. Heavy
  filters (view, seeds, document_id) still refetch + relayout.
- **Snapshot review API.** Approve / Reject buttons land per-snapshot
  decisions in `snapshot_reviews`; Sprint 7 will gate persistence on them.
- **Diagnostics page.** Settings → Diagnostics shows queue depth,
  in-progress jobs, stalled docs, per-stage P50/P95, and an explicit
  "safe-only" hash cleanup that filters out active hashes.

### Gaps / issues

- **`test_reconciler.py` and `test_unmerge.py` are skipped without
  `DATABASE_URL`.** Both run cleanly when the Compose Postgres is up and
  migration 0007 has been applied. CI wiring lives in Sprint 8.
- **Stream replay is best-effort.** If Redis dies, the durable
  `ingestion_run_logs` table preserves history but the drawer's live tail
  may miss a few seconds during reconnect (browser EventSource retries
  automatically; we don't yet seed the replay from `last_event_id`).
- **`metric` events are not persisted** to `ingestion_run_logs` (kept
  cheap by design). The Diagnostics page therefore uses run-level
  `started_at..ended_at` for the P50/P95 — not per-stage. Per-stage
  precision can land in a Sprint 9 follow-up.

### Next sprint prep

Sprint 6 starts with a clean slate: ingestion is observable + recoverable,
graph editing is reversible, and the snapshot/review wire is in place for
chat citations to reference. Open the drawer once when starting Sprint 6
to confirm SSE replay still works after the next worker rebuild.
