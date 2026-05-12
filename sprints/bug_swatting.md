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
