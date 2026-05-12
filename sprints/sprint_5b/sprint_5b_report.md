# Sprint 5b report

**Status**: Complete (implementation + docs + tests).
**Build**: `pnpm run build` — green.
**Tests**: `pnpm run test:pipeline` — **27 passed, 6 skipped**
(integration-style tests skip without `DATABASE_URL`).

## Shipped

| Area | Summary |
| ---- | ------- |
| **Migration** | `0007_ingestion_observability` adds `ingestion_runs.last_heartbeat_at`, `ingestion_run_logs`, `merge_audit_log`, `snapshot_reviews`; seeds `pipeline_settings.graph_extract_concurrency=4` and `notes_llm_streaming=true`. |
| **Tasks (`apps/pipeline/app/tasks.py`)** | Centralised `_mark_task_failed` helper, `_Heartbeat` async context, `_ensure_arq_pool` lazy fallback, dedicated `asyncio.CancelledError` branches in all three tasks, `FileNotFoundError` short-circuit in `parse_document`, FK-race tolerance in `generate_atomic_notes`, parallel `extract_graph` via `asyncio.Semaphore`, per-episode `log` + `metric` events, `reconcile_stuck_documents` cron. |
| **Notes synthesis (`notes_llm.py`)** | `stream=True` with `timeout=120 s` / `max_retries=1`; per-50-tokens progress callback. Feature-flagged on `pipeline_settings.notes_llm_streaming`. |
| **Events fabric (`job_redis.py` / `jobs_stream.py`)** | `record_log` and `record_metric` helpers fan out to pub/sub, Redis Stream (`MAXLEN ~ 1000`), and `ingestion_run_logs`. SSE generator replays via `XRANGE` then tails pub/sub. Job hashes get a 7-day NX TTL. |
| **Merge audit (`merge_audit_repo.py`)** | New table + insert helper; merge call paths now capture victim payload, survivor pre-merge fields, victim provenance, incident relationships. |
| **Unmerge** | `unmerge_entity` and `unmerge_note` restore the victim row, re-attach provenance, roll back survivor fields, mark the audit row undone. Routed through `POST .../graph/entities/{id}/unmerge` and `POST .../notes/{id}/unmerge`. |
| **Graph search (`internal_graph.internal_graph_search`)** | `GET /graph/search` calls Graphiti hybrid `search()` scoped to the workspace `group_id`; returns edges joined to Postgres entity IDs. |
| **Snapshot review** | `POST .../snapshots/{id}/review` + `snapshot_reviews` upsert; Sprint 7 will gate persistence on the decision. |
| **Diagnostics admin (`internal_admin.py`)** | `GET /internal/v1/admin/diagnostics` (arq queue + in-progress, stalled docs, latency, hash counts); `POST .../cleanup-stale-job-hashes` filtered to terminal-status only. |
| **Web — JobLogConsole** | Bottom-drawer drawer with multi-job SSE, follow-tail, filter chips, copy-to-clipboard via toast, localStorage persisted collapse state. Mounted in `workspace-shell.tsx` at z-35. |
| **Web — Diagnostics page** | `/settings/diagnostics` polls the admin endpoint every 8 s; shows queue/stalled/latency tables and the "Clean terminal hashes" button. |
| **Web — Merge dialogs** | "Full undo" CTA next to the existing "Revert survivor fields" in both entity and note merge dialogs. |
| **Web — Graph canvas** | `ChipFilterApplier` toggles `hidden` per node/edge for entity types / edge types; only the heavy filters (view, seeds, document_id, valid_at, node_limit, depth) trigger a refetch + relayout. |
| **Web — Graph filter bar** | 300 ms debounced auto-apply for chip filters; "Apply filters" still drives the heavy query. |
| **Tests** | `test_arq_dedup.py`, `test_cancelled_error_handling.py`, `test_reconciler.py` (DB-dependent), `test_unmerge.py` (DB-dependent), `test_graph_search.py`, `test_stream_replay.py`. |
| **Docs** | `specs/apis.md` marks `/graph/search`, `/snapshots/{id}/review`, both unmerge routes Sprint 5b implemented. `README.md` gains an Ingestion Observability + Merge Undo section. |

## Definition of Done

- All Sprint 5b plan items landed and are surfaced in
  [`sprint_5b_tasks.md`](sprint_5b_tasks.md) with file references.
- Bugs surfaced during the Sprint 5 debugging marathon are now structurally
  impossible (dedup), recoverable (reconciler + heartbeat), or visible in
  the UI (drawer + diagnostics).
- `pnpm run build` green; `pytest` green (27/6 skipped — DB-dependent tests
  run when `DATABASE_URL` is set and migration 0007 has been applied).

## Follow-ups (deferred)

- Per-stage P50/P95 instead of run-level. Needs the worker to mark stage
  boundaries with the time stamp; trivial follow-up.
- "Replay since `last_event_id`" for the SSE — currently we replay the last
  ~200 events on subscribe, which is enough for the drawer's UX.
- Snapshot review workflow gating in the PersistenceJob flow (Sprint 7).
- `GET /graph/search` UI integration in the graph filter bar (the endpoint
  is wired; surfacing it via a search input is Sprint 6 chat work).

## Notes

- Migration `0007_ingestion_observability` must run before the new
  pipeline + worker images do anything useful — the heartbeat column,
  `ingestion_run_logs`, `merge_audit_log`, and `snapshot_reviews` are all
  referenced by the new code. Compose's one-shot `migrate` service still
  handles this automatically.
- The new code is defensive about migrations not yet applied (e.g.
  `merge_audit_log` writes use a try/except so a dev DB without 0007 still
  permits merge; unmerge then returns 404).
