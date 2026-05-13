# zkast — Technical Debt Log

Use this file for **non-blocking** refactors, dependency upgrades, and cleanup discovered during sprints. Do **not** block planned sprint tasks on items here unless they become critical.

## How to add an entry

| Field | Description |
| ----- | ----------- |
| **ID** | `TD-XXX` (increment manually) |
| **Date** | When noticed |
| **Area** | web / pipeline / infra / specs |
| **Description** | What should change |
| **Reason** | Why it matters |
| **Suggested sprint** | When to address |

## Entries

### TD-001 — Ingestion observability: streaming console panel
- **Date**: 2026-05-12
- **Area**: web + pipeline
- **Description**: Build a collapsible "build log" drawer that streams `log` /
  `metric` events from the worker per stage and per episode. Pub/sub →
  Redis Streams (`XADD MAXLEN`) for replay; durable `ingestion_run_logs`
  table for post-mortem.
- **Reason**: During Sprint 5 we lost ~1h to "is it stuck?" diagnostics that
  required `docker compose exec redis-cli` + `psql`. A glance at a UI drawer
  should answer it. ~80% of the SSE plumbing already exists (`publish_job_event`,
  `/internal/v1/jobs/{id}/events`, `JobStreamBridge`).
- **Status**: **Resolved in Sprint 5b** — `job-log-console.tsx`, Redis
  Stream replay, `ingestion_run_logs` table, plus `record_log` /
  `record_metric` helpers in `job_redis.py`.

### TD-002 — Worker-crash reconciler + ingestion run heartbeats
- **Date**: 2026-05-12
- **Area**: pipeline
- **Description**: Periodic sweep that marks `documents` in active states as
  `failed` when there's no matching arq job in flight AND no recent
  `ingestion_runs.last_heartbeat_at` update. Adds the heartbeat column and a
  10s heartbeat coroutine inside each task.
- **Reason**: Sprint 5 saw documents stuck on `generating_notes` indefinitely
  because the worker crashed between `enqueue_job` and the next stage's first
  event. Postgres lied to the UI for ~7 minutes.
- **Status**: **Resolved in Sprint 5b** — `_Heartbeat` async context
  manager + `reconcile_stuck_documents` arq cron + `last_heartbeat_at`
  column in migration 0007.

### TD-003.5 — Task handlers don't catch `asyncio.CancelledError`
- **Date**: 2026-05-12
- **Area**: pipeline
- **Description**: All three pipeline task handlers in
  [`apps/pipeline/app/tasks.py`](../apps/pipeline/app/tasks.py) used
  `except Exception as exc:`. Python 3.8+ made `asyncio.CancelledError` a
  `BaseException` subclass, so worker SIGTERM (rebuild, scale, OOM-kill)
  didn't trigger the failure handler — documents stayed at their
  in-progress status with `failure_reason=NULL` forever.
- **Status**: **Resolved in Sprint 5b** — dedicated
  `except asyncio.CancelledError` branch in all three tasks marks the
  document failed with `failure_reason='cancelled_by_worker_shutdown'`
  before re-raising. Covered by `test_cancelled_error_handling.py`.

### TD-003 — FK race: `generate_atomic_notes` vs. cascading document delete
- **Date**: 2026-05-12
- **Area**: pipeline
- **Description**: Catch `psycopg.errors.ForeignKeyViolation` per-note when
  inserting `note_episodes`, log `note_skipped_provenance_gone`, continue.
  Also pre-check `documents.status` is active at task start.
- **Status**: **Resolved in Sprint 5b** — `generate_atomic_notes` now
  pre-checks `_is_document_active` and wraps each `insert_note` call in
  a per-note try/except that logs `note_skipped_provenance_gone` and
  continues. Same FK-tolerance applied to `extract_graph` entity/edge
  inserts.

### TD-004 — `worker_startup` failure → `KeyError('arq_pool')` in tasks
- **Date**: 2026-05-12
- **Area**: pipeline
- **Description**: A transient Redis hiccup at worker boot left
  `ctx["arq_pool"]` unset; subsequent jobs crashed with an opaque
  `KeyError`.
- **Status**: **Resolved in Sprint 5b** — `worker_startup` re-raises on
  pool creation failure so the arq supervisor restarts the worker
  (fail-fast). Each task also calls `_ensure_arq_pool(ctx)` which lazily
  creates the pool if missing and emits a `worker_startup_miss_recovered`
  warning.

### TD-005 — Bounded parallelism + streaming Cohere for ingestion
- **Date**: 2026-05-12
- **Area**: pipeline
- **Description**: Serial `extract_graph` + non-streaming, no-timeout
  Cohere notes synthesis caused 5–15 min stage times and silent 30 min
  retries on hung calls.
- **Status**: **Resolved in Sprint 5b** — `extract_graph` uses
  `asyncio.gather` + `asyncio.Semaphore(pipeline_settings.graph_extract_concurrency)`
  (default 4, max 8). `notes_llm.py` streams Cohere chat with
  `timeout=120` and `max_retries=1`, calling a token-counter progress
  callback every ~50 tokens.

### TD-006 — Stale Redis `zkast:job:*` hashes accumulate forever
- **Date**: 2026-05-12
- **Area**: pipeline
- **Description**: Apply 7d NX EXPIRE on first `job_hset`; ship a
  Diagnostics admin action to clean terminal hashes.
- **Status**: **Resolved in Sprint 5b** — `job_hset` sets a 7-day NX
  TTL on every first write (`job_redis.py`); per-job Redis Stream
  inherits the same TTL. New `POST /internal/v1/admin/cleanup-stale-job-hashes`
  is filtered to `status IN ('succeeded','failed','cancelled')` (never
  touches a live ingestion); wired into Settings → Diagnostics.

### TD-007 — `_job_id` collision regression test
- **Date**: 2026-05-12
- **Area**: pipeline tests
- **Status**: **Resolved in Sprint 5b** —
  [`tests/test_arq_dedup.py`](../apps/pipeline/tests/test_arq_dedup.py)
  pins (a) stage-suffixed chained enqueues never collide, (b) a same-key
  re-enqueue returns `None`, (c) the worker wrapper turns `None` into a
  loud `RuntimeError`.

### TD-008 — Real merge undo (restore deleted victim row)
- **Date**: 2026-05-12
- **Area**: pipeline + web
- **Status**: **Resolved in Sprint 5b** — new `merge_audit_log` table
  captures the victim payload + survivor pre-merge fields + victim
  provenance during every merge. `POST /graph/entities/{id}/unmerge` and
  `POST /notes/{id}/unmerge` restore the victim row, re-attach
  provenance, and roll back the survivor's fields. UI surfaces both
  "Full undo" and "Revert survivor fields" in the merge dialogs.

### TD-009 — Hidden-attribute graph filter (no relayout/refetch)
- **Date**: 2026-05-12
- **Area**: web
- **Status**: **Resolved in Sprint 5b** — `ChipFilterApplier` (in
  `graph-canvas.tsx`) toggles `hidden` per node/edge using
  `graph.setNodeAttribute`. Only the heavy filters (view, seeds,
  document_id, valid_at, node_limit, depth) trigger a refetch + relayout.

### TD-010 — Graphiti edge-timestamp 400 storm against Cohere
- **Date**: 2026-05-12
- **Area**: pipeline + upstream library
- **Description**: `graphiti_core.utils.maintenance.edge_operations._extract_edge_timestamps`
  calls the underlying LLM client (Cohere via OpenAI-compatible adapter)
  with a `response_format.json_schema` whose `object` type has no
  `required` field. Cohere rejects it with
  `400 invalid 'json_schema' provided: 'object' type must have at least one
  required field`. Graphiti retries 2× per edge, fails, logs
  `Failed to extract timestamps for edge <uuid>`, and moves on. This burns
  ~10–20s per failed edge and is the dominant cost in `extract_graph` on
  Cohere — a 20-page PDF that should take ~2 minutes takes 10+.
- **Reason**: With this fixed, the per-stage timeouts in BUG-006 can be
  tightened significantly (graph stage back toward 5–10 min instead of 40).
  It also restores edge `valid_from` / `valid_to` data that we lose today.
- **Suggested sprint**: Sprint 6 or 7 — either monkey-patch Graphiti's
  `_extract_edge_timestamps` to inject `required` into the JSON schema, or
  switch the Graphiti LLM client to Cohere's native client which uses a
  different schema shape. Upstream issue worth filing.
- **Status**: Open

### TD-012 — Checkpoint episode progress for resumable graph extraction
- **Date**: 2026-05-12
- **Area**: pipeline
- **Description**: `extract_graph` is now resilient to per-episode failures
  (BUG-008 fix), but a hard failure or worker shutdown still restarts the
  entire graph stage from episode 0 on retry. With Cohere costs and
  Graphiti's slow per-edge processing, this is wasteful. Idea: persist a
  per-`ingestion_run` set of completed episode UUIDs (Redis Set or a new
  `ingestion_run_episode_progress` table); when the stage starts, skip
  episodes already in the set; `_process_episode` adds the episode UUID
  to the set on success. The "Retry from stage" UI already exists — this
  would make it cheap.
- **Reason**: Today a 90% success run still requires re-extracting the
  successful 90% on retry. Worst case: a 20-minute graph stage that fails
  on the last episode costs 40 minutes total. With checkpointing it costs
  ~22.
- **Suggested sprint**: Sprint 6 or 7.
- **Status**: Open

### TD-011 — Add an end-to-end smoke test for the pipeline-log SSE drawer
- **Date**: 2026-05-12
- **Area**: web tests
- **Description**: BUG-007 happened because no test exercises the full
  EventSource path from `JobLogConsole` through the Next.js proxy. A
  Playwright (or even a node + `eventsource` library) smoke test that uploads
  a tiny PDF, asserts the drawer registers an active job, and asserts at
  least one `log` event lands in the drawer would have caught the missing
  `?workspaceId=` query parameter immediately.
- **Reason**: The drawer is now the primary "is it stuck?" tool; if it
  silently breaks again, sprints lose hours on the same diagnostic detour
  we just resolved.
- **Suggested sprint**: Sprint 6.
- **Status**: Open
