# zkast — Bug Swatting Log

Log **critical bugs that block sprint progress** here. Resume sprint work after fix + commit referencing the Bug ID.

## Entry template

```markdown
## Bug Entry: YYYY-MM-DD
- **ID**: BUG-XXX
- **Description**: ...
- **Discovered**: ...
- **Context**: Sprint N, ...
- **Fix**: ...
- **Status**: Resolved | Open
```

## Entries

## Bug Entry: 2026-05-13
- **ID**: BUG-012
- **Description**: After BUG-011 unblocked retrieval, every chat turn that
  reached the LLM step failed with
  `TypeError: object async_generator can't be used in 'await' expression`.
  Root cause: ``cohere.AsyncClientV2.chat_stream`` is declared
  ``async def chat_stream(...) -> typing.AsyncIterator[V2ChatStreamResponse]``
  in the Cohere v5 SDK, which the Cohere SDK compiles into an
  **async-generator function**, not a plain coroutine — calling it returns
  the async iterator *synchronously*. Our wrapper at
  `apps/pipeline/app/cohere_chat.py` did `await client.chat_stream(...)`,
  which raises immediately. `chat_stream_grounded` then propagated the
  error and the chat-turn handler ran the "failed" path with the
  ``TypeError`` as the user-visible failure reason.
  The non-streaming fallback (`client.chat`) really *is* a coroutine
  function so the second leg of the BUG-009 fallback was correct — the
  bug only fires on the primary streaming path.
- **Discovered**: Manual smoke after BUG-011 fix — graphiti search
  returned 5 hits for "Deloitte", the turn passed refusal, then died on
  the very first Cohere call.
- **Context**: Sprint 6 (chat turn wrapper). Hidden behind BUG-011 until
  the FalkorDB database-naming bug was fixed.
- **Fix**: Call `client.chat_stream(...)` directly (no `await`). Keep
  the transient-error retry by wrapping the synchronous call in a tiny
  ad-hoc retry loop (one re-open on transient errors). Updated
  `tests/test_chat_turn_empty_stream_fallback.py` to mock
  `chat_stream` with `MagicMock(return_value=…)` (sync, mirrors the
  real Cohere shape) instead of `AsyncMock`, and pinned the contract
  with a comment so a future refactor can't quietly reintroduce
  the wrong shape.
- **Status**: Resolved

## Bug Entry: 2026-05-13
- **ID**: BUG-011
- **Description**: Every chat turn refused with "No grounding context found"
  even though the workspace graph clearly had relevant entities (e.g.
  asking "what does Deloitte have to do with oil & gas?" against a
  workspace with a `Deloitte` Entity node + three `Deloitte`-mentioning
  `RELATES_TO` edges returned `total_candidates=0`).
  Root cause: graphiti-core 0.29.0's `FalkorDriver` silently calls
  `self.driver = self.driver.clone(database=group_id)` inside
  `Graphiti.add_episode` ([graphiti.py L1034](https://github.com/getzep/graphiti))
  whenever `group_id != driver._database`. Our
  `falkor_database_for_workspace(ws)` returned `f"zkast_ws_{ws.replace('-', '')}"`
  while `group_id = workspace_id` (with dashes), so:
    - **Writes** during `add_episode` were silently re-routed to a
      FalkorDB graph named after the bare workspace UUID
      (`00000000-0000-4000-8000-000000000002`) — 373 entities, 563 edges
      landed there.
    - **Reads** via `graphiti.search(group_ids=[ws])` still went through
      the originally-configured graph `zkast_ws_*`, which was empty.
  The `/graph/search` and chat-retrieval endpoints both returned
  `[]` for *every* query, in *every* workspace. The graph **viz** was
  unaffected because it reads `entities` / `relationships` straight from
  Postgres.
- **Discovered**: Sprint 6 smoke test against the user's Oil & Gas
  workspace — every chat turn returned `total_candidates: 0`, even for
  queries that matched obvious entities visible in the legend.
- **Context**: Sprint 6 (uncovered) / Sprints 4–5c (latent since the
  prefixed naming has shipped since Sprint 2).
- **Fix**: `falkor_database_for_workspace(ws)` now returns the workspace
  UUID verbatim
  ([`apps/pipeline/app/graphiti_factory.py`](../apps/pipeline/app/graphiti_factory.py)).
  Database name == group_id, so the silent clone is a no-op, writes and
  reads land on the same graph, and existing data is reached without
  re-ingestion. Also surfaced retrieval hit-count as a `warning`-level
  log event from `chat_turn` into the JobLogConsole drawer so a future
  zero-hit regression is loud, not silent
  ([`apps/pipeline/app/chat_turn.py`](../apps/pipeline/app/chat_turn.py)).
- **Status**: Resolved

## Bug Entry: 2026-05-12
- **ID**: BUG-010
- **Description**: Sprint 5c Phase 1 introduced typed entity extraction via
  `graphiti.add_episode(entity_types=ENTITY_TYPES, edge_types=EDGE_TYPES, …)`.
  The Pydantic models in
  [`apps/pipeline/app/entity_schemas.py`](../apps/pipeline/app/entity_schemas.py)
  declared all fields as `Optional[str] = Field(default=None, ...)`, so the
  JSON schemas Pydantic emits have an empty `required: []` array. Cohere's
  OpenAI-compat endpoint rejects those with HTTP 400 *"invalid 'json_schema'
  provided: object type must have at least one required field"*. Graphiti
  retries 2× then surrenders for that LLM call, so every per-episode entity
  + edge extraction returned an empty list. Result: 33 episodes processed,
  **0 entities, 0 edges, 0 evidence_spans_linked**.
- **Discovered**: User noticed the JobLogConsole drawer was reporting
  `episode N/33: +0 entities, +0 edges` for every chunk. Worker stderr
  showed `Error in generating LLM response: Error code: 400 - ... invalid
  'json_schema' provided: object type must have at least one required
  field` for every Graphiti call.
- **Context**: Same root cause as TD-010 (Graphiti's internal
  `_extract_edge_timestamps`), but the typed-extraction path made the
  problem block **every** call rather than just edge timestamps. So the
  graph went from "slow but populated" pre-Sprint-5c to "fast but empty"
  post-Sprint-5c.
- **Fix**: Added a single required field per model in
  [`apps/pipeline/app/entity_schemas.py`](../apps/pipeline/app/entity_schemas.py):
  - Every entity type model gets `description: str = Field(...)`
    (no default), except `Standard` which already had a required
    `identifier`.
  - Every edge type model gets `rationale: str = Field(...)`.
  The LLM can always fill these from the source context; they're distinct
  from Graphiti's own `EntityNode.name` so no collision.
- **Status**: Resolved
- **Follow-up**: Two new regression tests in
  [`tests/test_typed_entities.py`](../apps/pipeline/tests/test_typed_entities.py)
  assert every entity type and every edge type has ≥ 1 required field in
  its JSON schema, so a future refactor that adds an all-optional model
  fails CI immediately rather than silently zeroing out extraction.

## Bug Entry: 2026-05-12
- **ID**: BUG-009
- **Description**: Notes stage failed with
  `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`. Root cause:
  Cohere's OpenAI-compatible streaming endpoint occasionally returns HTTP
  200 with zero content chunks when called with
  `response_format={"type":"json_object"}` and `stream=True`. Sprint 5b's
  streaming code in
  [`apps/pipeline/app/notes_llm.py`](../apps/pipeline/app/notes_llm.py)
  appended deltas into a `buf` list; when the stream produced no deltas,
  `raw_text` was the empty string and `_extract_json_object("")` raised
  immediately. The empty-response edge case had no fallback path.
- **Discovered**: User retry after BUG-008's resilience fixes. Drawer
  surfaced "Notes Job failed: JSONDecodeError: Expecting value:
  line 1 column 1 (char 0)" — the message itself was a clue (the parser
  saw nothing to parse).
- **Context**: Sprint 5b post-merge polish.
- **Fix**: Restructured `generate_notes_from_episodes` so both the
  streaming and non-streaming paths share one `client.chat.completions.create`
  invocation per attempt:
  1. If `streaming=True` and the buffer comes back empty, log a
     `notes_llm_empty_stream_fallback_to_nonstreaming` warning and retry
     with `stream=False`.
  2. If the response (streaming or not) is unparseable JSON and we used
     streaming, retry once non-streaming with the same prompt.
  3. If both paths produce empty content, raise a `RuntimeError` that
     mentions Cohere / API key / quota so the operator-facing
     `failure_reason` is actionable.
- **Status**: Resolved
- **Follow-up**: 3 new regression tests in
  [`apps/pipeline/tests/test_notes_generation.py`](../apps/pipeline/tests/test_notes_generation.py)
  pin (a) empty-stream fallback, (b) unparseable-stream fallback,
  (c) both-paths-empty raises a clear error.

## Bug Entry: 2026-05-12
- **ID**: BUG-008
- **Description**: `extract_graph` aborted on episode 25/33 with an empty
  `failure_reason` ("Job failed:" with nothing after the colon). Two
  underlying problems:
  1. A single transient `httpx.ConnectError` while
     `clients.embedder.create_batch` was reaching out to Cohere during
     Graphiti's `_semantic_candidate_search`. `httpx.ConnectError()` has no
     message, so `str(exc)` was the empty string and the failure_reason
     column was blank.
  2. The episode ran inside `asyncio.gather(*tasks)` (no
     `return_exceptions=True`), so the one failure tore down all 30
     in-flight episodes and threw away ~5 minutes of work (42 entities,
     12 edges).
- **Discovered**: User retry after BUG-006's timeout fix. Drawer showed
  "Job failed:" with no detail. Worker logs revealed the
  `httpcore.ConnectError → httpx.ConnectError` chain originating in
  `app/cohere_adapters.py:41`.
- **Context**: Sprint 5b post-merge polish.
- **Fix**:
  1. `_describe_exception(exc)` helper in
     [`apps/pipeline/app/tasks.py`](../apps/pipeline/app/tasks.py) returns
     `"<TypeName>: <message>"` (or just `<TypeName>` when the message is
     empty) so `failure_reason` is never blank. Wired into all three
     stage handlers (`parse_document`, `generate_atomic_notes`,
     `extract_graph`).
  2. New `_post_json_with_retry` helper in
     [`apps/pipeline/app/cohere_adapters.py`](../apps/pipeline/app/cohere_adapters.py)
     wraps both `CohereEmbedder.create_batch` and `CohereCrossEncoder.rank`
     with 3-attempt exponential backoff (1s/2s/4s with ±25% jitter).
     Retries `ConnectError`, `ConnectTimeout`, `ReadTimeout`,
     `WriteTimeout`, `PoolTimeout`, `RemoteProtocolError`, plus 5xx and
     429. Bubbles 4xx (auth / validation) immediately to avoid burning
     budget on permanent errors.
  3. `asyncio.gather(...)` in `extract_graph` now uses
     `return_exceptions=True`. Per-episode/per-note failures are tallied;
     the run only fails outright when **zero** items succeed. Partial
     failures emit a `warning` log with the failure count and the first
     error type. `CancelledError` is re-raised immediately (never
     swallowed by partial-success logic).
- **Status**: Resolved
- **Follow-up**: TD-012 ("Checkpoint episode progress so retries resume
  from the failed episode rather than from scratch") added to
  `sprints/tech_debt.md`. Regression tests live in
  [`apps/pipeline/tests/test_failure_resilience.py`](../apps/pipeline/tests/test_failure_resilience.py).

## Bug Entry: 2026-05-12
- **ID**: BUG-006
- **Description**: `extract_graph` consistently failed at ~5 minutes with
  `failure_reason='cancelled_by_worker_shutdown'` even though the worker
  process was alive and heartbeating throughout. Root cause: arq's default
  `job_timeout` is **300 seconds**, and `WorkerSettings` did not override it.
  arq wraps every task in `asyncio.wait_for(..., timeout=job_timeout)`; when
  the timeout fires it cancels the task, which raises `asyncio.CancelledError`
  *inside* the task — indistinguishable from a SIGTERM. Sprint 5b's
  CancelledError handler caught it correctly but mislabeled it as a worker
  shutdown.
- **Discovered**: User reported "ingestion failed after 4–5 minutes, 130
  entities, 67 edges, then `cancelled_by_worker_shutdown`". Worker logs
  showed only cron activity, no SIGTERM, no docker restart — ruling out the
  shutdown explanation. The 5-minute mark is the smoking gun for arq's
  default budget. Slow Graphiti `_extract_edge_timestamps` retries
  (Cohere returns `400 invalid json_schema` per edge → 2 retries × ~5s) burn
  through the 300s budget before the per-episode loop can finish.
- **Context**: Sprint 5b polish (post-merge). The Sprint 5b heartbeat +
  reconciler infrastructure correctly caught the resulting failure, but the
  underlying ceiling was wrong.
- **Fix**:
  1. Wrapped each task in `arq.worker.func()` with explicit per-stage
     timeouts in [`apps/pipeline/app/tasks.py`](../apps/pipeline/app/tasks.py)
     — parse 600s, notes 1200s, graph 2400s.
  2. Added `WorkerSettings.job_timeout = 2400` as a global ceiling.
  3. New `_classify_cancel_reason(stage, elapsed_s)` helper picks
     `cancelled_by_job_timeout` vs `cancelled_by_worker_shutdown` based on
     how close elapsed time is to the per-stage budget, so the operator-facing
     `failure_reason` is accurate. Elapsed/budget are also added to the log
     `data` payload and the SSE event.
  4. Fixed the reconciler cron config from `minute=set(range(60))` to
     `cron(reconcile_stuck_documents, second=0)` — the previous spec caused
     a startup catch-up burst of ~10 runs in 5 seconds.
- **Status**: Resolved
- **Follow-up**: TD-010 ("Graphiti edge-timestamp 400 storm") will let us
  tighten these budgets back down once Graphiti stops burning ~15s per
  failed edge.

## Bug Entry: 2026-05-12
- **ID**: BUG-007
- **Description**: `JobLogConsole` drawer always showed "Waiting for events…"
  because `useEventSource` built its URL as
  `/api/v1/jobs/{jobId}/events` without the `?workspaceId=<uuid>` query
  parameter that the Next.js proxy in
  [`apps/web/src/app/api/v1/jobs/[jobId]/events/route.ts`](../apps/web/src/app/api/v1/jobs/[jobId]/events/route.ts)
  requires. The proxy returned HTTP 400 immediately, the browser closed the
  EventSource silently, and the drawer stayed empty even though the Redis
  Stream `zkast:jobs:<id>:log` had 100+ events queued and pub/sub had a
  live subscriber.
- **Discovered**: User reported the drawer was empty during a fresh
  ingestion. Confirmed via `redis-cli XLEN`, `PUBSUB NUMSUB`, and reading
  the proxy route source.
- **Context**: Sprint 5b polish — the SSE wiring shipped without an
  end-to-end smoke check.
- **Fix**: Added `workspaceId: string` to the `ActiveJob` shape in
  [`apps/web/src/lib/job-events.tsx`](../apps/web/src/lib/job-events.tsx);
  threaded it through both `registerActiveJob` call sites in
  [`apps/web/src/components/documents-panel.tsx`](../apps/web/src/components/documents-panel.tsx);
  `JobLogConsole.useEventSource` now includes `?workspaceId=...` in the URL.
  `loadFromStorage` filters out legacy entries that lack `workspaceId` so
  pre-fix localStorage entries are pruned silently on next page load.
- **Status**: Resolved

## Bug Entry: 2026-05-12
- **ID**: BUG-001
- **Description**: Pipeline stages 2 and 3 were silently no-op'd by arq's
  `_job_id` deduplication. Every chained `pool.enqueue_job(...)` reused the
  parent SSE job id as `_job_id`; after `parse_document` finished, arq saw a
  cached result under that key and dropped the next-stage enqueue, returning
  `None`. The task didn't check the return value and unconditionally updated
  `documents.status` to the next stage, leaving the document stuck (e.g.
  `generating_notes`) with `arq:queue=0, arq:in_progress=empty`.
- **Discovered**: During Sprint 5 — user reported "stuck on Generating Notes
  for 7 minutes" with no worker activity. Confirmed via Redis (`LLEN
  arq:queue` = 0, `ZRANGE arq:in_progress` = empty) and absent
  `stage_started: generating_notes` worker log line.
- **Context**: Sprint 5 — Graph Visualization, Editing, and Snapshots. Not
  in scope for Sprint 5; surfaced because user was actively testing the
  graph view against fresh ingests.
- **Fix**: Stage-suffixed dedup keys — `_job_id=f"{job_id}:parse"`, `:notes`,
  `:graph` — at all five enqueue sites
  ([`apps/pipeline/app/tasks.py`](../apps/pipeline/app/tasks.py) ×2,
  [`apps/pipeline/app/internal_ingestion.py`](../apps/pipeline/app/internal_ingestion.py) ×3).
  Added a `RuntimeError` when `pool.enqueue_job(...)` returns `None` inside
  `parse_document` and `generate_atomic_notes` so any future regression is
  loud, not silent.
- **Status**: Resolved
- **Follow-up**: Regression test → TD-007 in [tech_debt.md](tech_debt.md).

## Bug Entry: 2026-05-12
- **ID**: BUG-003
- **Description**: Worker SIGTERM mid-flight (rebuild, restart, OOM-kill)
  left documents zombied at their in-progress status with
  `failure_reason=NULL`. Root cause: Python 3.8+ made
  `asyncio.CancelledError` a `BaseException` subclass; the existing
  `except Exception as exc:` handler did not catch it, so the failure
  path that updates `documents.status='failed'` never ran. arq logged
  the traceback and shut down cleanly, the row was left in limbo until
  manual intervention.
- **Discovered**: Sprint 5 debugging on 2026-05-12 — confirmed by grep
  of `docker compose logs worker` showing the `asyncio.CancelledError`
  traceback at the exact UTC timestamp recorded in `documents.updated_at`.
- **Context**: Sprint 5b ingestion robustness work.
- **Fix**: Dedicated `except asyncio.CancelledError:` branch in all three
  task handlers in
  [`apps/pipeline/app/tasks.py`](../apps/pipeline/app/tasks.py). Marks
  the document failed with reason `cancelled_by_worker_shutdown`, then
  re-raises so arq still sees the cancellation. Regression test:
  [`tests/test_cancelled_error_handling.py`](../apps/pipeline/tests/test_cancelled_error_handling.py).
- **Status**: Resolved

## Bug Entry: 2026-05-12
- **ID**: BUG-004
- **Description**: FK violation crashing `generate_atomic_notes`:
  `insert or update on table "note_episodes" violates foreign key
  constraint "note_episodes_episode_id_fkey"`. Root cause: the task
  reads episodes into memory, the document is force-deleted (or its
  ingestion run is restarted) which cascades-deletes the episodes,
  then the task wakes and tries to insert `note_episodes` referencing
  the now-deleted episode IDs. The whole stage fails.
- **Discovered**: Surfaced in the Sprint 5 stale-hash Redis dump
  (multiple `kind=generate_atomic_notes, status=failed` entries with
  the FK error in `progress.error`).
- **Context**: Sprint 5b ingestion robustness work.
- **Fix**: Pre-check in
  [`apps/pipeline/app/tasks.py`](../apps/pipeline/app/tasks.py)
  `generate_atomic_notes` short-circuits with a recoverable failure if
  `_is_document_active` returns false at the start. Each `insert_note`
  call is also wrapped in a try/except `psycopg.errors.ForeignKeyViolation`
  that logs `note_skipped_provenance_gone` and continues. Same FK
  tolerance applied to `extract_graph` entity/edge inserts.
- **Status**: Resolved

## Bug Entry: 2026-05-12
- **ID**: BUG-005
- **Description**: `parse_document` could crash with `KeyError('arq_pool')`
  on the first job after a transient Redis hiccup at worker boot. Root
  cause: `worker_startup` swallowed `create_pool(...)` failures silently;
  arq still picked up jobs and they failed reading `ctx["arq_pool"]`.
- **Discovered**: One such hash observed in Sprint 5 dump
  (`{"percent": 0, "stage": "parsing", "error": "'arq_pool'"}`).
- **Context**: Sprint 5b ingestion robustness work.
- **Fix**: `worker_startup` re-raises so the arq supervisor restarts
  the worker (fail-fast). Each task additionally calls
  `_ensure_arq_pool(ctx)` which lazily creates the pool if missing and
  logs a structured `worker_startup_miss_recovered` warning so a
  transient failure doesn't permanently break the worker.
- **Status**: Resolved

## Bug Entry: 2026-05-12
- **ID**: BUG-002
- **Description**: After deleting a document with `cascade=exclusive_derivatives`,
  the graph view still showed orphan entities/relationships from the deleted
  document. The cascade routine ran orphan cleanup **before**
  `delete_document_row`, so episodes still existed at scan time and nothing
  looked orphaned. After the document delete fired its `ON DELETE CASCADE`
  on `episodes`, the now-orphaned entity/relationship rows were left behind.
- **Discovered**: Sprint 5 — user deleted all documents and notes, but graph
  panel still showed entities (NERC, FERC, EPRI, "Materials Research Focus
  Areas") on the working graph.
- **Context**: Sprint 5.
- **Fix**: Split [`apps/pipeline/app/cascade.py`](../apps/pipeline/app/cascade.py)
  into `execute_exclusive_derivatives_delete` (notes only, pre-delete) and
  `cleanup_orphan_graph_rows` (entities + relationships, **post-delete**).
  Reordered call sites in
  [`internal_ingestion.py`](../apps/pipeline/app/internal_ingestion.py) to:
  notes → `delete_document_row` → orphan cleanup. Preserves user-edited
  entities (`is_user_edited=true`) and manual edges (`origin='manual'`).
  Added user-facing "Clean orphan rows" button + endpoint as fallback for
  legacy stuck rows.
- **Status**: Resolved
