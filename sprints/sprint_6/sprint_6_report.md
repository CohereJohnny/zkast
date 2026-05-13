# Sprint 6 report

**Status**: Implementation complete on branch `sprints/sprint-6`.
**Build**: web `tsc --noEmit` green; pipeline suite is 65 passed / 14 skipped on host, including 10 new tests for the chat-turn path.
**Migrations to apply on review**: `0009_chat_tables`.
**Container rebuild required**: pipeline + worker (new `cohere>=5,<6` dep, new `chat_turn` task wired into `WorkerSettings.functions`) and web (new chat components + API proxies).

## Goal

Backend-first **chat turn** end-to-end: hybrid retrieval → Cohere Rerank (via existing Graphiti search path) → Cohere v2 chat with documents + grounded citations; persist `ChatSession`, `ChatMessage`, `RetrievalRecord`, `ChatCitation`; SSE streaming with seven event types; cooperative stop; refusal when no context — covering **FR-35 – FR-39, FR-41, FR-45** and **US-8.1, US-8.2, US-8.4, US-8.8, US-8.9**.

## Shipped

| Phase | Area | Summary |
| ----- | ---- | ------- |
| **0** | Paperwork | Branch `sprints/sprint-6` off `main` (which carries `sprint-5c`). Cohere native SDK pinned via `cohere>=5,<6` in [`apps/pipeline/requirements.txt`](../../apps/pipeline/requirements.txt). |
| **1** | Migration `0009` | New [`0009_chat_tables`](../../apps/migrations/alembic/versions/0009_chat_tables.py): `chat_sessions`, `chat_messages`, `retrieval_records`, `chat_citations` with CHECK constraints, `ON DELETE CASCADE`, and a partial unique index `(session_id, sequence) WHERE is_active_alternate = true`. `chat_messages.retrieval_mode` ships now (DEFAULT `'graph'`) so Sprint 6b can flip on RAG-mode without a follow-up migration. |
| **2a** | Cohere chat wrapper | New [`apps/pipeline/app/cohere_chat.py`](../../apps/pipeline/app/cohere_chat.py) — native v2 `AsyncClientV2.chat_stream` + `chat`; transient retry helper mirroring `cohere_adapters._post_json_with_retry`; **BUG-009 empty-stream fallback** to non-streaming with a `warning` callback into the JobLogConsole drawer; defensive citation extractor that tolerates both `start/end/text/sources[]` shapes Cohere has shipped in practice. |
| **2b** | Repos | New [`chat_repo.py`](../../apps/pipeline/app/chat_repo.py) (sessions + messages + citations) and [`retrieval_repo.py`](../../apps/pipeline/app/retrieval_repo.py) (RetrievalRecord). Sync psycopg style — same pattern as `notes_repo.py` / `evidence_repo.py`. |
| **2c** | Turn orchestration | New [`apps/pipeline/app/chat_turn.py`](../../apps/pipeline/app/chat_turn.py) — single arq task `run_chat_turn` covering retrieval, document assembly with token budget + smallest-first ordering, **`RetrievalRecord` persisted before any LLM call (FR-41)**, refusal short-circuit (no Cohere call), streaming generation, citation mapping via prefixed `note:` / `entity:` / `relationship:` / `episode:` ids, `_classify_cancel_reason` for arq job-timeout vs worker-shutdown classification (reused from `tasks.py`), and final message persistence. Seven SSE events fan out through `publish_job_event` / `record_log` — so the existing JobLogConsole drawer **also** shows chat-turn activity. |
| **2d** | Internal router | New [`apps/pipeline/app/internal_chat.py`](../../apps/pipeline/app/internal_chat.py) — workspace-scoped routes for create / list / get / patch sessions, submit message (returns `{user_message, assistant_message, turn_id}` + 202), cancel turn (sets Redis flag), and `GET .../chat-messages/{id}/retrieval` for the future retrieval inspector. `_job_id` is prefixed `chat:<turnId>` to avoid colliding with ingestion stages. |
| **2e** | Wire-up | `internal_chat_router` registered in `main.py`; 501 `/internal/v1/chat/turns` stub deleted. `run_chat_turn` added to `WorkerSettings.functions` via `arq_func(timeout=1800, max_tries=1)`. |
| **3a** | Web proxies | Five new route files under `apps/web/src/app/api/v1/workspaces/[workspaceId]/`: `chat-sessions/route.ts`, `chat-sessions/[sessionId]/route.ts`, `chat-sessions/[sessionId]/messages/route.ts`, `chat/turns/[turnId]/route.ts` (SSE — passes `?workspaceId=` upstream per BUG-007), `chat/turns/[turnId]/cancel/route.ts`. All zod-validate UUIDs and call `requireMatchingWorkspace`. |
| **3b** | Client SSE | New [`apps/web/src/lib/chat-stream.ts`](../../apps/web/src/lib/chat-stream.ts) — `useChatStream(workspaceId, turnId, callbacks)` opens `EventSource`, parses each JSON payload, dispatches by `type` to seven typed callbacks, auto-closes on `message_complete` / `job_failed` / `job_cancelled`. Callbacks held in a ref so re-renders that change identity don't tear down the stream. |
| **3c** | Components + page | New [`chat-panel.tsx`](../../apps/web/src/components/chat-panel.tsx), [`chat-citation.tsx`](../../apps/web/src/components/chat-citation.tsx), [`chat-scope-picker.tsx`](../../apps/web/src/components/chat-scope-picker.tsx). Replaced the `/chat` placeholder. `ChatScopePicker` dogfoods all four Sprint 5c filter pickers + a snapshot combobox + a `valid_at` date input. ChatPanel has a throttled `aria-live` region (~150 ms), inline citation chips with hover cards, distinct refusal / failed / streaming visual states, and a Stop button visible only while streaming. |
| **4** | Tests | 10 new pipeline tests in `apps/pipeline/tests/test_chat_*.py` covering all six DoD invariants (see below). Full suite: **65 passed, 14 skipped, 0 failed**. Web `tsc --noEmit`: 0 errors. |

## Definition-of-done check

- [x] **Empty corpus → explicit refusal** (US-8.9, FR-45) — pinned by `test_chat_turn_refusal.py`: zero documents → `chat_stream_grounded` not called, message `status='refused'`, `message_complete{finish_reason: "refused"}` event.
- [x] **Stop button cancels within 1s** (US-8.8) — `cancel` POST sets `zkast:job:<turnId>:cancel` Redis flag; arq surfaces `CancelledError`; handler classifies via `_classify_cancel_reason("chat_turn", elapsed_s)`, marks message `status='cancelled'` with a populated `failure_reason` (BUG-008 guard), emits `job_cancelled`, re-raises. Pinned by `test_chat_turn_cancellation.py`.
- [x] **Retrieval inspector data identical on reopen** (US-8.4 AC-3, FR-41) — `RetrievalRecord` is persisted **before** the first Cohere call. Pinned by `test_retrieval_record_persistence.py` (happy + failure paths).
- [x] **Citation document_ids unambiguous** — every grounding document uses a prefixed id (`note:<uuid>`, etc.). `_map_source_ids_to_sources` reverse-maps prefix → `kind`. Pinned by `test_chat_turn_citation_mapping.py`.
- [x] **Empty Cohere stream survives** (BUG-009 pattern reused) — `cohere_chat.chat_stream_grounded` falls back to non-streaming `chat`, fires `on_warning`, returns a populated `ChatStreamResult` with `used_streaming=False`. Pinned by `test_chat_turn_empty_stream_fallback.py`.
- [x] **Scope flows through retrieval + persists on the message** — `effective_scope_snapshot` column carries the JSON; `retrieval_mode` column ships defaulting to `'graph'`. Pinned by `test_chat_scope_filtering.py`.
- [x] **JobLogConsole drawer shows chat-turn events for free** — the SSE proxy targets `/internal/v1/jobs/{turnId}/events`, the same channel the drawer already subscribes to.
- [x] Pipeline + web typechecks clean.
- [ ] **Manual smoke** — pending user validation on the branch (same workflow as Sprint 5b / 5c).

## Files

### Migrations
- [`apps/migrations/alembic/versions/0009_chat_tables.py`](../../apps/migrations/alembic/versions/0009_chat_tables.py)

### New pipeline modules
- [`apps/pipeline/app/cohere_chat.py`](../../apps/pipeline/app/cohere_chat.py)
- [`apps/pipeline/app/chat_repo.py`](../../apps/pipeline/app/chat_repo.py)
- [`apps/pipeline/app/retrieval_repo.py`](../../apps/pipeline/app/retrieval_repo.py)
- [`apps/pipeline/app/chat_turn.py`](../../apps/pipeline/app/chat_turn.py)
- [`apps/pipeline/app/internal_chat.py`](../../apps/pipeline/app/internal_chat.py)

### Modified pipeline modules
- [`apps/pipeline/app/main.py`](../../apps/pipeline/app/main.py) — register `internal_chat_router`, remove 501 stub
- [`apps/pipeline/app/tasks.py`](../../apps/pipeline/app/tasks.py) — import `run_chat_turn`, add `arq_func(run_chat_turn, timeout=1_800, max_tries=1)` to `WorkerSettings.functions`
- [`apps/pipeline/requirements.txt`](../../apps/pipeline/requirements.txt) — `cohere>=5,<6`

### New web API proxies
- `apps/web/src/app/api/v1/workspaces/[workspaceId]/chat-sessions/route.ts`
- `apps/web/src/app/api/v1/workspaces/[workspaceId]/chat-sessions/[sessionId]/route.ts`
- `apps/web/src/app/api/v1/workspaces/[workspaceId]/chat-sessions/[sessionId]/messages/route.ts`
- `apps/web/src/app/api/v1/workspaces/[workspaceId]/chat/turns/[turnId]/route.ts`
- `apps/web/src/app/api/v1/workspaces/[workspaceId]/chat/turns/[turnId]/cancel/route.ts`

### New web components + lib
- [`apps/web/src/lib/chat-stream.ts`](../../apps/web/src/lib/chat-stream.ts)
- [`apps/web/src/components/chat-panel.tsx`](../../apps/web/src/components/chat-panel.tsx)
- [`apps/web/src/components/chat-citation.tsx`](../../apps/web/src/components/chat-citation.tsx)
- [`apps/web/src/components/chat-scope-picker.tsx`](../../apps/web/src/components/chat-scope-picker.tsx)

### Modified web pages
- [`apps/web/src/app/(workspace)/chat/page.tsx`](../../apps/web/src/app/(workspace)/chat/page.tsx) — replaces the empty placeholder with `<ChatPanel workspaceId=…>`

### Tests (10 new, all on host runner — no DB / Redis / Cohere required)
- [`apps/pipeline/tests/test_chat_turn_refusal.py`](../../apps/pipeline/tests/test_chat_turn_refusal.py)
- [`apps/pipeline/tests/test_chat_turn_citation_mapping.py`](../../apps/pipeline/tests/test_chat_turn_citation_mapping.py)
- [`apps/pipeline/tests/test_chat_turn_cancellation.py`](../../apps/pipeline/tests/test_chat_turn_cancellation.py)
- [`apps/pipeline/tests/test_chat_turn_empty_stream_fallback.py`](../../apps/pipeline/tests/test_chat_turn_empty_stream_fallback.py)
- [`apps/pipeline/tests/test_retrieval_record_persistence.py`](../../apps/pipeline/tests/test_retrieval_record_persistence.py)
- [`apps/pipeline/tests/test_chat_scope_filtering.py`](../../apps/pipeline/tests/test_chat_scope_filtering.py)

## How to deploy

```bash
# 1. Apply the new migration
docker compose run --rm migrate

# 2. Rebuild pipeline + worker (new `cohere>=5,<6` dep, new `run_chat_turn` task)
docker compose up -d --build pipeline worker

# 3. Rebuild web (new chat components + API proxies)
docker compose up -d --build web

# 4. Hard refresh the browser, open /chat, type a question.
```

## Known follow-ups

- **Sprint 6b — GraphRAG vs regular RAG eval.** `chat_messages.retrieval_mode` already ships defaulting to `'graph'`. 6b adds the `rag` path + a small canned question set + a side-by-side comparison view.
- **Sprint 7 — Chat polish.** Chat Home (session list), drawer mode in the three-panel layout, regeneration with `is_active_alternate` (column already in `0009`), share visibility UI, persistence writer to external Neo4j / AGE.
- Reverse-proxy SSE config note (`proxy_buffering off` for nginx) — to be added to the README's deploy section when the first hosted environment is stood up. Dev `docker-compose` is not affected.

## Risks accepted / mitigated this sprint

| Risk | Outcome |
|---|---|
| Cohere v2 `chat_stream` event shape unstable | Wrapped via `_safe_attr` to tolerate both dict + pydantic; both citation event names (`citation-start` / `citation`) handled defensively. |
| Citation `document_ids` opaque | Built grounding documents with explicit prefixed `id` (`note:<uuid>` etc.) — reverse map is deterministic. |
| Token-budget blowups | Smallest-first ordering + per-turn budget (default 6 000 tokens via `pipeline_settings.chat_doc_token_budget`); excess truncated. |
| Empty Cohere stream | BUG-009 pattern reused: empty stream → single non-streaming retry → `warning` log event into the drawer. |
| FR-41 violation under refactor | Two regression tests pin the call order (`insert_retrieval_record` strictly before `chat_stream_grounded`), including a failure-path test that asserts the record is persisted even when Cohere throws. |
| Session orphans on workspace delete | FK CASCADE on every chat table per migration `0009`. |
| Arq dedup collision | `_job_id = "chat:<turn_id>"` namespaced; `_enqueue_chat_turn` raises 409 if `enqueue_job` returns `None`. |
