# Sprint 9 — Pre-planning notes (draft)

> **Not a task plan.** Captured during Sprint 5 work so context isn't lost. The
> formal `sprint_9_tasks.md` will be authored at the close of Sprint 5 using
> these notes as input.
>
> **Note about [sprintplan.md](../sprintplan.md):** the current P1 outline puts
> Sprint 9 on **multi-user auth (Epic 6)**. Everything below is ingestion
> observability / robustness — it surfaced during Sprint 5 debugging and was
> tagged "Sprint 9" colloquially. When planning, decide whether to:
> 1. Re-theme Sprint 9 around ingestion (and slide auth to Sprint 10/11), or
> 2. Open a new "Sprint 8.5 / 9b" ingestion sprint, or
> 3. Split — some items into Sprint 8 polish, others into Sprint 9.
>
> All items here are P0/P1 quality-of-life. None unblocks v0.1.0 release.

---

## Theme

**"Make ingestion observable, recoverable, and predictable."**

During Sprint 5 we hit a string of issues where the only diagnosis path was
`docker compose exec redis redis-cli ...` + raw `psql` queries. Users (and us)
should know what the pipeline is doing without leaving the UI, and stuck states
should self-correct or fail loudly instead of silently lying.

Three sub-themes:

| Sub-theme | Outcomes |
| --- | --- |
| **A. Streaming console** | Per-job, per-stage, per-episode logs visible in the UI; collapsible drawer; persistent history. |
| **B. Robustness** | Failed enqueues, crashed workers, mid-flight cascades all surface as `documents.status = failed` within seconds, not hours. |
| **C. Performance** | Parallelize the only serial loop that matters (`extract_graph`); add real timeouts to long Cohere calls. |

---

## A. Streaming console panel

### Goal

A bottom-of-screen, collapsible "build log" drawer that streams worker activity
in real time. Users open it when they wonder "is it stuck?" — the answer should
be visible in one glance.

### Why now

Sprint 5 produced two extended "is it stuck?" episodes that consumed >30 minutes
of debugging time each. Both would have been **5-second glances** at a console
panel.

### What's already in place

About 80% of the plumbing exists today:

```
worker (arq task) ──publish──► Redis pub/sub: zkast:jobs:<job_id>
                              └► Redis hash:   zkast:job:<job_id>
       pipeline FastAPI ◄──── subscribe + replay hash
                  GET /internal/v1/jobs/{id}/events   (SSE)
                            ▲ proxy
                  /api/v1/jobs/{jobId}/events
                            ▲ EventSource
                  JobStreamBridge / future LogConsole
```

Concrete references:

- Pub/sub primitives: [`apps/pipeline/app/job_redis.py`](../../apps/pipeline/app/job_redis.py) (`publish_job_event`, `job_hset`).
- SSE endpoint: [`apps/pipeline/app/internal_jobs.py`](../../apps/pipeline/app/internal_jobs.py) (`GET /internal/v1/jobs/{id}/events`, `StreamingResponse`).
- Web proxy: [`apps/web/src/app/api/v1/jobs/[jobId]/events/route.ts`](../../apps/web/src/app/api/v1/jobs/%5BjobId%5D/events/route.ts).
- Existing consumer: `JobStreamBridge` in [`apps/web/src/components/documents-panel.tsx`](../../apps/web/src/components/documents-panel.tsx) (reads `type`, `percent`, `job_completed`, `job_failed`).

### What's missing

1. **Fine-grained event types.** Today the worker only emits `stage_started`,
   `stage_completed`, `job_completed`, `job_failed` for the three pipeline
   stages. We need:
   - `log` events: `{level, message, ts}` — free text status (Cohere call
     start/end, parse N pages, rate-limit retry, etc.).
   - `metric` events: `{name, value}` — `notes_emitted`, `edges_emitted`,
     `tokens_consumed`, `episode_index_n_of_m`.
2. **Per-episode emit points.** Currently the entire `extract_graph` loop
   produces **two** events (start, complete) over potentially 10-30 minutes.
   Two-line change: emit a `log` after each `graphiti.add_episode(...)` with
   the per-episode `{nodes, edges}` count. See [Item C2](#c2-per-episode-progress-events) below.
3. **History / replay.** Redis pub/sub is fire-and-forget; opening the console
   late shows nothing. Two solid options:
   - **Capped Redis Stream** per job (`XADD zkast:jobs:<id>:log MAXLEN ~ 1000`)
     so SSE clients can `XREAD` from `0` and tail. Cheapest, matches "build
     log" feel.
   - **Durable table** `ingestion_run_logs` (`id, ingestion_run_id, ts, level,
     stage, message, data jsonb`) for queryability and post-mortem. More work,
     more value long-term.
   - Recommended: do **both** — stream is the live wire, table is the audit
     log, populated by the same emit call. Stream is read by SSE; table is
     read by a "view full log" detail page.
4. **`JobLogConsole` client component.** Collapsible bottom drawer:
   - Multi-job subscribe (one ingestion may chain three jobs; UI should
     coalesce or tab them).
   - Monospace lines, level-coloured using existing `success`/`warning`/`danger`
     tokens.
   - Auto-scroll with "pause on hover" + explicit "follow tail" toggle.
   - Filter by stage or level.
   - Persist collapsed/expanded state in `localStorage` (mirror the documents
     panel pattern in [`workspace-main-grid.tsx`](../../apps/web/src/components/workspace-main-grid.tsx)).
   - Cross-wire to the existing `zkast:graph-invalidated` event so a "N notes
     emitted" line in the log can also kick the graph canvas refresh.

### Sizing

| Piece | Effort |
| --- | --- |
| Add `log`/`metric` event types + emit through all three workers | S |
| Switch pub/sub to Redis Streams + replay on subscribe | S |
| Persistent `ingestion_run_logs` table + repo | S |
| `JobLogConsole` component + collapsible drawer + multi-job subscribe | M |
| Cross-wire log → graph invalidation | XS |

Total: **roughly one focused sprint** scoped to ingestion logs only (no chat
session logs yet — that lands when chat ships).

### Anti-pattern reminder (UX skill)

Don't ship `window.alert/prompt/confirm` here either — we already built
[`feedback-provider.tsx`](../../apps/web/src/components/feedback-provider.tsx)
with `useToast`/`useConfirm`/`usePrompt`. Reuse it for any console actions
like "Cancel job", "Copy log to clipboard", etc.

---

## B. Robustness / self-healing

### B1. Worker-crash reconciler

**Problem.** Documents can sit in active statuses (`queued`, `parsing`,
`generating_notes`, `extracting_graph`, `building_graph`) with **no** matching
arq job in flight. We hit this **three times** in Sprint 5:

- arq killed mid-task → restart did not re-pick the in-flight job.
- `pool.enqueue_job(..., _job_id=<collision>)` returned `None` silently (the
  bug we fixed by suffixing `_job_id` per stage).
- **2026-05-12 ~04:13 UTC**: worker process restarted (likely
  `docker compose up -d --build worker` to pick up the dedup fix) during a
  running `extract_graph`. Document stayed at `building_graph` with
  `failure_reason=NULL` indefinitely. Diagnosis required correlating:
  `documents.updated_at`, `ZRANGE arq:in_progress`, `docker compose logs`
  grep for `←`/`!` markers, and entity-count `SELECT count(*)`. **This is
  the exact UX cost the reconciler should eliminate.**

The UI fakes a progress bar forever because `documents.status` says it's
running but `arq:queue=0, arq:in_progress=empty`.

**Proposed fix.** Periodic sweep (every 30s in the worker, or a cron arq job):

1. Query Postgres for `documents` in active statuses, joined with their latest
   `ingestion_runs`.
2. For each, check Redis: is `<job_id>:<stage>` in `arq:in_progress`? Was its
   heartbeat updated within last N minutes? (Heartbeat = a field on
   `ingestion_runs` written every 10s by the running task; see below.)
3. If neither, mark `documents.status = 'failed'` with
   `failure_reason = 'worker_crashed_during_<stage>'` and
   `ingestion_runs.status = 'failed', ended_at = now()`.

**Companion:** add an `ingestion_runs.last_heartbeat_at` column. Each running
task wraps its loop with a `heartbeat()` coroutine that updates the column
every 10s. The reconciler uses `now() - last_heartbeat_at > 90s` as the
stalled-without-crash signal too (covers hung Cohere calls).

### B2. FK race in `generate_atomic_notes`

**Observed.** Multiple stale job hashes in Redis with this error:

```
insert or update on table "note_episodes" violates foreign key constraint
"note_episodes_episode_id_fkey"
DETAIL: Key (episode_id)=(7d73379e-...) is not present in table "episodes".
```

**Root cause.** Race between:
1. `generate_atomic_notes` reads episodes into memory.
2. Sends Cohere request (10-60s synthesis).
3. Document is force-deleted (or its `ingestion_run` is restarted, or a
   `replaces_document_id` upload arrives) → `ON DELETE CASCADE` removes
   episodes.
4. Task wakes up, tries `INSERT INTO note_episodes (note_id, episode_id) VALUES
   ($1, $2)` referencing now-deleted episodes → FK violation, whole task
   fails.

**Proposed fixes (pick one or both):**

- **Per-note catch.** Wrap each `insert_note(..., episode_ids=...)` in a
  `try/except psycopg.errors.ForeignKeyViolation`. Log structured warning
  `note_skipped_provenance_gone` with note title + episode_id. Continue. Don't
  fail the whole stage for one missing chunk.
- **Pre-check.** At the top of `generate_atomic_notes`, re-fetch
  `documents.status` and short-circuit to `cancelled` if the document is no
  longer active. Cheap, covers the most common case.

References:
- Loop: [`apps/pipeline/app/tasks.py`](../../apps/pipeline/app/tasks.py)
  `generate_atomic_notes` — the `for payload in note_payloads:` loop.
- Cascade chain: [`apps/migrations/alembic/versions/0005_notes_graph.py`](../../apps/migrations/alembic/versions/0005_notes_graph.py)
  (`note_episodes ON DELETE CASCADE`).

### B2.5. `asyncio.CancelledError` not caught by task handlers

**Problem.** Python 3.8+ made `asyncio.CancelledError` a subclass of
`BaseException`, not `Exception`. Our three pipeline tasks all use
`except Exception as exc:` for their failure handler. When the worker is
SIGTERM'd mid-loop (e.g. `docker compose up -d --build worker`), arq cancels
the running task → `CancelledError` is raised → not caught → re-raised
uncaught → **`documents.status` stays at its in-progress value, `failure_reason`
stays NULL, no `job_failed` event published.**

**Observed.** 2026-05-12 04:13:21 UTC — `extract_graph` for
`Sample Deep Research Report.pdf` was cancelled by a worker restart picking
up the dedup fix. Document stayed at `building_graph` with null
`failure_reason` for 18+ minutes until the user retried manually.
`docker compose logs worker | grep -i CancelledError` showed the traceback;
our `except Exception` block never ran.

**Proposed fix.** Two-line addition per task handler:

```python
try:
    # … work …
except asyncio.CancelledError:
    await update_document(..., status="failed",
                          failure_reason="cancelled_by_worker_shutdown")
    await publish_job_event(redis, job_id, "job_failed",
                            reason="cancelled_by_worker_shutdown",
                            stage="<stage>")
    raise  # re-raise so arq still sees the cancellation
except Exception as exc:  # noqa: BLE001
    # existing handler, unchanged
```

Apply to `parse_document`, `generate_atomic_notes`, `extract_graph` in
[`apps/pipeline/app/tasks.py`](../../apps/pipeline/app/tasks.py). Complementary
to B1 (reconciler) — together they ensure a worker restart never leaves a
document in a zombie state.

### B3. `KeyError: 'arq_pool'` on worker startup race

**Observed.** Stale job hash:
```
{"percent": 0, "stage": "parsing", "error": "'arq_pool'"}
```

That's `KeyError('arq_pool')` str-ified — `ctx["arq_pool"]` not set when the
task ran.

**Root cause.** `worker_startup` in [`tasks.py`](../../apps/pipeline/app/tasks.py)
sets `ctx["arq_pool"] = await create_pool(_redis_settings_for_worker())`. If
that call raised (transient Redis hiccup at boot), arq still happily picks up
jobs but they crash deep inside `parse_document` reading `ctx["arq_pool"]`.

**Proposed fix.** Either:
- **Fail-fast.** Re-raise in `worker_startup` so arq supervisor restarts the
  worker. Add a structured `worker_startup_failed` log line first.
- **Lazy fallback.** Guard each consumer:
  ```python
  pool = ctx.get("arq_pool") or await create_pool(_redis_settings_for_worker())
  if "arq_pool" not in ctx:
      logger.warning("arq_pool_recovered_after_startup_miss")
  ```

The lazy fallback keeps work flowing during transient Redis blips; the
fail-fast surfaces "your Redis URL is wrong" faster. Recommend **both** —
fail-fast + a recovery shim, with the shim emitting a `metric` event so the
console panel shows it.

### B4. Storage file race on force-delete

**Observed.** Stale hash:
```
{"percent": 0, "stage": "parsing",
 "error": "no such file: '/var/zkast/storage/.../<doc_id>.pdf'"}
```

**Root cause.** Force-delete removes the PDF file from disk; an in-flight
`parse_document` then tries to `fitz.open(path)`. The unconditional `os.unlink`
in [`internal_ingestion.py`](../../apps/pipeline/app/internal_ingestion.py)
delete handler doesn't coordinate with the worker.

**Proposed fix.** Same shape as B2: catch `FileNotFoundError` in
`parse_document`, log a `pdf_storage_gone_mid_parse` warning, abort cleanly
with `documents.failure_reason='source_pdf_deleted'` instead of a Python
traceback.

Lower priority than B2/B3 because force-delete is a user-initiated, eyes-on
action.

### B5. Stale job hash TTL

**Observed.** 31+ `zkast:job:*` hashes in Redis after a half-day of work, many
in inconsistent states from earlier bugs.

**Proposed fix.** In `job_hset`, set an `EXPIRE` (e.g. 7 days) on first write:

```python
async def job_hset(redis, job_id, **fields):
    key = job_hash_key(job_id)
    mapping = _flatten_mapping(fields)
    if mapping:
        await redis.hset(key, mapping=mapping)
        await redis.expire(key, 7 * 24 * 3600, nx=True)  # only on first set
```

Pair with a `cleanup_orphan_job_hashes` admin tool reachable from a Settings
page (defer to Sprint 10 polish).

**Footgun caught during Sprint 5 debugging.** A naive
`redis-cli --scan --pattern 'zkast:job:*' | xargs DEL` blows away **live**
SSE hashes too, freezing the UI's progress bar even though the underlying
arq task is still chugging through `extract_graph`. The worker doesn't crash
(it does its own bookkeeping in `arq:in_progress`), and the hash is
re-created on the next `job_hset` (typically the final `status=succeeded`
write) — but the user loses live progress visibility in between. **The
admin cleanup tool MUST filter to "safe to delete" hashes only:**

- Has a terminal `status` (`succeeded` / `failed` / `cancelled`), AND
- Its arq job key (`<job_id>:<stage>`) is not in `arq:in_progress`, AND
- Optional age threshold (`updated_at` field, or hash TTL near zero).

The CLI escape hatch (for self-hosters debugging) should be a separate
`force` mode with a big warning.

### B6. arq dedup-key collision guard (already partially fixed)

We fixed [`tasks.py`](../../apps/pipeline/app/tasks.py) and
[`internal_ingestion.py`](../../apps/pipeline/app/internal_ingestion.py)
to use stage-suffixed `_job_id` (`f"{job_id}:parse"`, `:notes`, `:graph`) and
added a `RuntimeError` when `pool.enqueue_job(...)` returns `None`.

**Sprint 9 follow-up:** add a unit test that constructs a known-collision
`_job_id` and asserts the chained enqueue raises. Don't ship the next bug
without coverage. See [BUG-001 in bug_swatting.md](../bug_swatting.md).

---

## C. Performance

### C1. Bounded parallelism on `extract_graph` episode loop

**Today.** The loop in [`tasks.py`](../../apps/pipeline/app/tasks.py)
`extract_graph` is fully serial:

```python
for ep in episodes:
    res = await graphiti.add_episode(...)        # ~10-30s per call
    for node in res.nodes: await asyncio.to_thread(upsert_entity_...)
    for edge in res.edges: await asyncio.to_thread(insert_relationship_...)
```

For a 19-page PDF with ~25 episodes and ~16 notes, this stage runs **5-15
minutes wall time** end-to-end. Graphiti's internal `SEMAPHORE_LIMIT=10` is
mostly idle because our outer loop is serial.

**Proposed fix.**

```python
sem = asyncio.Semaphore(4)  # well below Graphiti's 10

async def process_episode(ep):
    async with sem:
        res = await graphiti.add_episode(...)
        # upsert serially per episode to keep entity-edge order
        for node in res.nodes: ...
        for edge in res.edges: ...

await asyncio.gather(*[process_episode(ep) for ep in episodes])
```

Expected: **3-4× speedup** for the stage (limited by Cohere RPM, not Python).
Trial first on a fixture workspace; monitor Cohere `429` rate; back off to
`Semaphore(2)` if rate-limit shows up.

**Companion:** make the semaphore size configurable via
`pipeline_settings.graph_extract_concurrency` (default 4, max 8).

### C2. Per-episode progress events

Two-line change in the same loop. Powers Item A.

```python
await publish_job_event(
    redis, job_id, "log",
    level="info",
    stage="extracting_graph",
    message=f"episode {i+1}/{n}: +{len(res.nodes)} entities, +{len(res.edges)} edges",
    data={"episode_index": i, "total": n,
          "entities": len(res.nodes), "edges": len(res.edges)},
)
```

Also emit a `metric` event with running totals so the console can show a real
progress bar within the stage.

### C3. Streaming Cohere chat for note synthesis

**Today.** [`notes_llm.py`](../../apps/pipeline/app/notes_llm.py) does **one**
non-streaming `chat.completions.create(...)` call per document. No `timeout=`,
no `max_retries=`, no progress signal until the entire JSON object comes back.
Default `AsyncOpenAI` timeout is 10 minutes × 3 retries silent — the original
"stuck 7 minutes" scenario.

**Proposed fix.**

1. Switch to `client.chat.completions.create(..., stream=True)`.
2. Set explicit `timeout=120.0` and `max_retries=1`.
3. Emit a `log` event every ~32 tokens (or every chunk boundary) with
   `received_tokens` running count — the console then shows the LLM actively
   producing text.
4. Parse the JSON only once `stream` is exhausted (Cohere closes the SSE
   stream with the final object).

Bonus: surface tokens-per-second as a `metric` event for back-of-envelope
performance debugging.

---

## D. Smaller follow-ups (don't lose)

### D1. Real merge undo (entities + notes)

Sprint 5 shipped **"revert survivor fields"** for both entity merge
([`entity-merge-dialog.tsx`](../../apps/web/src/components/entity-merge-dialog.tsx))
and note merge ([`note-merge-dialog.tsx`](../../apps/web/src/components/note-merge-dialog.tsx)).
That only PATCHes the survivor back to its pre-merge field values; the deleted
victim row is **not** restored.

True undo would need internal endpoints:
- `POST .../graph/entities/{id}/unmerge` with the original other-entity payload.
- `POST .../notes/{id}/unmerge` similarly.

Snapshot tables already hold per-entity payloads — repurpose the same payload
shape so unmerge re-inserts the victim and rewires its provenance.

### D2. Hidden-attribute filtering on graph canvas

Sprint 5 plan called for "attribute-driven `hidden` flag on graph filter
change" so we don't refetch + relayout. Current implementation refetches from
`/graph` on each filter change. Works fine for current workspace sizes but
breaks the "60fps at 5k nodes" NFR-4.

Sigma supports per-node `hidden` attribute; implementation is straightforward
once we wire `graph-filter-bar` to call `graph.setNodeAttribute(id, 'hidden',
!matchesFilter)` instead of triggering a refetch.

### D3. `GET /graph/search` endpoint (hybrid)

Documented in [`specs/apis.md`](../../specs/apis.md) under Knowledge Graph but
not implemented. Graphiti `search()` is a natural fit. Likely lives more
naturally with Sprint 6 (chat retrieval).

### D4. Snapshot review workflow

`POST /snapshots/{id}/review` is in [`specs/apis.md`](../../specs/apis.md) but
deferred from Sprint 5 per its report. Pairs with Sprint 7 persistence.

### D5. `GraphFilterBar` only emits via "Apply filters" button

Today filter changes require an explicit click. Consider debounced
auto-apply (300ms) for `view`, `entity_types`, `edge_types`. Keep the button
for chunkier filters (seed entity IDs, valid_at).

### D6. Settings panel — "Diagnostics" section

A small admin-ish page that surfaces:
- Active arq queue depth + in-progress job list.
- Stalled documents (matches B1 reconciler signal).
- Redis hash hygiene (count + cleanup button — see B5).
- Per-stage rolling P50/P95 wall time from `ingestion_run_logs`.

Could be gated to owner role; useful for self-hosters debugging their stack.

---

## E. Open questions to resolve before planning

1. **Sprint 9 theme conflict** — multi-user auth (current sprintplan.md) vs.
   ingestion observability (this doc). Pick one; carry the other to the next
   slot.
2. **Streams vs. database for log history** — go with both, or stream-only
   for v0.1.0?
3. **Per-stage concurrency** — make it a `pipeline_settings` field or a
   global env var?
4. **Console drawer placement** — bottom drawer (terminal feel) or right rail
   below the graph panel? Skill says bottom for "build log" pattern.
5. **Multi-doc concurrency in worker** — today arq runs one job at a time per
   worker process. Should Sprint 9 also bump worker process count via
   `WorkerSettings.max_jobs`? Probably yes once C1 lands — the parallel
   episodes will quickly saturate one process.

---

## F. Already done in Sprint 5 (don't redo)

These were caused by issues uncovered in this same debugging session and have
been fixed inline. Listed here so Sprint 9 planning doesn't relitigate them.

- arq dedup-key collision (`_job_id=job_id` reused across stages) → fixed
  with stage suffix; new `RuntimeError` if enqueue returns `None`. See
  [BUG-001](../bug_swatting.md).
- Orphan-graph cleanup race (cascade ran before doc delete, missed orphans) →
  fixed by reordering + new `cleanup_orphan_graph_rows` + `Clean orphan rows`
  UI button. See [BUG-002](../bug_swatting.md).
- Native `alert/confirm/prompt` everywhere → replaced with
  [`feedback-provider.tsx`](../../apps/web/src/components/feedback-provider.tsx).
  Reuse this in Sprint 9, don't reintroduce browser popups.
- Graph not refreshing after document delete / ingestion completion → new
  `emitGraphInvalidated` event bus in
  [`apps/web/src/lib/graph-events.ts`](../../apps/web/src/lib/graph-events.ts).
- Force-delete checkbox for mid-ingestion documents (cancels run + flips doc
  to `failed`) → already shipped.
- Duplicate graph panel on `/graph` → already fixed in
  [`workspace-main-grid.tsx`](../../apps/web/src/components/workspace-main-grid.tsx).

---

## G. Source diagnostic recipes (keep until console panel ships)

Until A1 lands, the diagnostic flow is:

```bash
# Active work?
docker compose exec -T redis redis-cli LLEN arq:queue
docker compose exec -T redis redis-cli ZRANGE arq:in_progress 0 -1

# Live tail
docker compose logs -f --tail=100 pipeline worker | grep -E \
  "stage_started|stage_completed|job_failed|extract|429|timeout|error"

# Real proof-of-life: do the row counts move?
watch -n 5 'docker compose exec -T postgres psql -U zkast -d zkast -tA -c "
  SELECT
    (SELECT count(*) FROM entities)         AS entities,
    (SELECT count(*) FROM relationships)    AS rels,
    (SELECT count(*) FROM entity_episodes)  AS ep_prov,
    (SELECT count(*) FROM atomic_notes)     AS notes,
    now()::text                             AS at;
"'

# Stuck-state inspection
docker compose exec -T postgres psql -U zkast -d zkast -c "
  SELECT id, original_filename, status, updated_at
  FROM documents
  WHERE status IN ('queued','parsing','generating_notes',
                   'extracting_graph','building_graph');
"

# Redis hash dump (use -T everywhere or you get 'input device is not a TTY')
docker compose exec -T redis sh -c \
  'for k in $(redis-cli --scan --pattern "zkast:job:*"); do
     echo "=== $k ==="; redis-cli HGETALL "$k";
   done' | head -200

# Cleanup arq result cache (safe — keys are stage-suffixed now)
docker compose exec -T redis sh -c \
  'redis-cli --scan --pattern "arq:job:*" | xargs -r -n 100 redis-cli DEL'
```

When the console panel ships, all of the above should be redundant for
diagnosing **active** jobs. Historical/forensic queries on
`ingestion_run_logs` remain useful.
