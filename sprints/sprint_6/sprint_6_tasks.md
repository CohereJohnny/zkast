# Sprint 6 — Grounded Chat (Core)

**Branch (planned)**: `sprints/sprint-6`
**Duration**: 2 weeks
**Goal**: Backend-first **chat turn** — hybrid retrieval → **Cohere Rerank** → **Cohere Chat** with documents + grounded citations; persist `ChatSession`, `ChatMessage`, `RetrievalRecord`, `ChatCitation`; **SSE** streaming with `retrieval_started`, `retrieval_complete`, `token`, `citation`, `message_complete`, `job_failed`, `job_cancelled`; cooperative stop; refusal when no context (**FR-35–FR-39**, **FR-41**, **FR-45**, **US-8.1**, **US-8.2**, **US-8.4**, **US-8.8**, **US-8.9**).

## Inputs

- Working graph + notes + LangExtract evidence from Sprints 4 / 5 / 5b / 5c.
- Typed Pydantic entity taxonomy (Sprint 5c) — used to boost typed-entity retrieval.
- Cohere integration from Sprint 2 (`embed-v4.0`, `rerank-v4.0-fast`, default chat `command-a-plus-05-2026` / `command-r7b-12-2024`).
- The `JobLogConsole` SSE replay pattern from Sprint 5b — re-use the same event-type / replay infrastructure for chat tokens.
- Filter picklists from Sprint 5c — reuse `EntityTypeahead` for optional session scope.

## Outputs

- A minimal but functional chat UI: single session, send message, stream answer, see citations mapped to note / document / entity / episode. Full polish (chat home, drawer, scope picker, regeneration) is **Sprint 7**.

## Dependencies

- Sprints 5 / 5b / 5c merged into `main` (done — tags `sprint-5b`, `sprint-5c`).
- Migration chain through `0008_entity_evidence` applied.

---

## Tasks

### Phase 0 — Paperwork

- [ ] Create branch `sprints/sprint-6` from `main`
- [ ] Confirm `specs/apis.md` Chat Sessions and `specs/datamodel.md` Chat sections are current (Sprint 5b/5c sync just landed)
- [ ] Confirm `apps/pipeline/app/main.py` no longer registers the `POST /internal/v1/chat/turns` 501 stub once the real route is wired in this sprint

### Phase 1 — Data + migrations

- [ ] **Migration `0009_chat_tables`** ([`apps/migrations/alembic/versions/0009_chat_tables.py`](../../apps/migrations/alembic/versions/)):
  - `chat_sessions(id, workspace_id FK, title, created_by_user_id FK?, scope JSONB, share_visibility, model_settings JSONB, created_at, updated_at, last_activity_at)` + indexes per `datamodel.md`.
  - `chat_messages(id, session_id FK, sequence, role, parent_message_id FK?, is_active_alternate, author_user_id FK?, content, status, failure_reason, effective_scope_snapshot JSONB, model_used, tokens_in, tokens_out, created_at, completed_at)` + unique (`session_id`, `sequence`) where `is_active_alternate = true`.
  - `retrieval_records(id, workspace_id FK, message_id FK unique, retrieval_strategy, query_text, retrieved_items JSONB, total_candidates, truncated, created_at)`.
  - `chat_citations(id, message_id FK, text_start, text_end, sources JSONB, created_at)`.
  - CHECK constraints + `ON DELETE CASCADE` per `datamodel.md` Chat section.
- [ ] Pipeline repo modules:
  - [ ] `apps/pipeline/app/chat_repo.py` — session + message + citation reads/writes.
  - [ ] `apps/pipeline/app/retrieval_repo.py` — append-only `RetrievalRecord` insert + read.

### Phase 2 — Pipeline service

- [ ] New module `apps/pipeline/app/internal_chat.py` (FastAPI router):
  - [ ] `POST /internal/v1/workspaces/{workspaceId}/chat-sessions` — create session; optional `title`, `scope`, `model_settings`, `seed_message`.
  - [ ] `GET /internal/v1/workspaces/{workspaceId}/chat-sessions[/{id}]` — list / detail.
  - [ ] `PATCH /internal/v1/workspaces/{workspaceId}/chat-sessions/{id}` — title / scope edits.
  - [ ] `POST /internal/v1/workspaces/{workspaceId}/chat-sessions/{id}/messages` — submit a user message; returns `{message_id, turn_id, stream_url}` and starts the turn in arq.
  - [ ] `POST /internal/v1/workspaces/{workspaceId}/chat/turns/{turnId}/cancel` — set `cancellation_requested_at`; the worker observes via cooperative `CancelledError`.
- [ ] New module `apps/pipeline/app/chat_turn.py` — single-turn execution:
  1. **Retrieve** — `graphiti.search()` hybrid (BM25 + vector + reranked) scoped by `session.scope` and `pinned_snapshot_id`. Reuse the Sprint 5b Cohere retry helper (`cohere_adapters._post_json_with_retry`) for the rerank call.
  2. **Document assembly** — render each hit (note / entity / relationship / episode) into a compact text "document" with stable id (`note:<uuid>`, `entity:<uuid>`, etc.). Apply per-turn token budget (configurable per workspace, default 6k tokens of grounding). Emit `retrieval_started` then `retrieval_complete` SSE events.
  3. **Persist `RetrievalRecord` before LLM call** — captures `query_text`, `retrieved_items[]` verbatim (with each item's `excerpt`), `total_candidates`, `truncated` (FR-41).
  4. **Generate** — Cohere `client.chat.stream(...)` with `documents=[...]` and grounded mode enabled. Stream `token` events as deltas arrive; map citation deltas to `ChatCitation` rows (`text_start`, `text_end`, `sources[]`) and emit `citation` events.
  5. **Finalize** — on stream close, mark `ChatMessage.status = complete` with `completed_at` and emit `message_complete`. Save `tokens_in` / `tokens_out`.
  6. **Refusal** — if `retrieved_items` is empty or below confidence threshold, skip the LLM call; persist a `refused` message and emit `message_complete` with `finish_reason: "refused"` (FR-45).
  7. **Empty-stream fallback** — same pattern as Sprint 5b's `notes_llm`: if the streamed buffer is empty when the stream closes, retry once with `stream=False` and surface a `warning` log event into the drawer.
- [ ] SSE event types (mirror Sprint 5b drawer; document in [`specs/apis.md`](../../specs/apis.md) Chat section if not already):

  | event `type` | payload | when |
  |---|---|---|
  | `retrieval_started` | `{ query_text }` | turn begins |
  | `retrieval_complete` | `{ retrieval_record_id, total_candidates, kept }` | after persist |
  | `token` | `{ delta }` | per Cohere chunk |
  | `citation` | `{ id, text_start, text_end, sources[] }` | per finalized span |
  | `message_complete` | `{ message_id, finish_reason, tokens_in, tokens_out }` | success |
  | `job_failed` | `{ reason }` | error |
  | `job_cancelled` | `{ reason }` | user stop or arq cancel |
- [ ] Cooperative cancellation: `CancelledError` handler mirrors `apps/pipeline/app/tasks.py` Sprint 5b pattern — mark `ChatMessage.status = cancelled` + persist `failure_reason: 'cancelled_by_user'` (or `cancelled_by_worker_shutdown` per `_classify_cancel_reason`), then re-raise.
- [ ] Conversation history: truncate prior messages to fit Cohere's input window with most-recent-first preference; insert summary placeholder for older turns. Retrieved documents always have priority over history per [`techstack.md`](../../specs/techstack.md).

### Phase 3 — Web tier

- [ ] API routes under `apps/web/src/app/api/v1/workspaces/[workspaceId]/`:
  - [ ] `chat-sessions/route.ts` — `GET` list, `POST` create.
  - [ ] `chat-sessions/[sessionId]/route.ts` — `GET` detail, `PATCH` edit.
  - [ ] `chat-sessions/[sessionId]/messages/route.ts` — `POST` submit user message, returns the `turn_id` + `stream_url`.
  - [ ] `chat/turns/[turnId]/route.ts` — `GET` SSE proxy with `text/event-stream`. **Must** include `?workspaceId=` query param on the upstream pipeline call (BUG-007 lesson).
  - [ ] `chat/turns/[turnId]/cancel/route.ts` — `POST` cancel.
- [ ] Client SSE parser hook (`apps/web/src/lib/chat-stream.ts`): wraps `EventSource` with reconnect + `Last-Event-ID`, parses each `data:` JSON, dispatches typed events to the consumer.
- [ ] Minimal `ChatPanel` (`apps/web/src/components/chat-panel.tsx`):
  - [ ] Input + transcript layout (centered column, max-w-3xl).
  - [ ] Streaming text appender with `aria-live="polite"` region throttled to avoid screen-reader spam (one announcement per ~150ms).
  - [ ] Inline citation chips that pop a hover card showing the cited `excerpt` + source kind/page.
  - [ ] **Stop** button visible while `status = streaming`; clicking POSTs cancel.
  - [ ] **Refusal** state: distinct visual (`useToast` info-variant or inline banner) so the user sees "no grounding found" rather than a confusing empty message.
- [ ] Reuse Sprint 5c `EntityTypeahead` in the (optional) "scope to entity" picker on session create — concrete dogfood of the new component.
- [ ] Reuse `useToast` for transient errors (failed turn, network blip, cancel confirmation).
- [ ] Route the chat surface at `/chat` (placeholder; full Chat Home is Sprint 7).

### Phase 4 — Infra + observability

- [ ] **Reverse proxy SSE config**: document `proxy_buffering off` for nginx (and the equivalent for Caddy / Traefik) in the README's deploy section. Confirm `docker-compose.yml` doesn't introduce a buffering proxy in front of the Next.js server.
- [ ] Wire chat-turn events into the same Redis Stream pattern Sprint 5b uses (`zkast:jobs:<turnId>:log`) so the existing `JobLogConsole` drawer **also** shows chat turn events when expanded. Free observability win.

### Phase 5 — Tests

- [ ] Pipeline tests (host runner, no DB required):
  - [ ] `tests/test_chat_turn_refusal.py` — retrieval returns 0 items → persist `refused` message, no Cohere call.
  - [ ] `tests/test_chat_turn_citation_mapping.py` — given a Cohere fixture response with two cited spans, assert two `chat_citations` rows with correct `text_start` / `text_end` / `sources[]`.
  - [ ] `tests/test_chat_turn_cancellation.py` — `CancelledError` propagates through the handler; message ends at `status=cancelled`.
  - [ ] `tests/test_chat_turn_empty_stream_fallback.py` — empty Cohere stream → non-streaming retry; second call returns content; success.
  - [ ] `tests/test_retrieval_record_persistence.py` — record is written **before** the LLM call (FR-41 ordering invariant).
- [ ] Web typecheck (`pnpm --filter web exec tsc --noEmit`) is clean.
- [ ] Manual smoke: ask a question about a freshly-ingested PDF, see ≥ 1 citation, click it to highlight the cited excerpt.

### Phase 6 — Docs + closeout

- [ ] Verify [`specs/apis.md`](../../specs/apis.md) Chat Sessions section is complete (already partly drafted); add the new SSE event types if missing.
- [ ] [`README.md`](../../README.md) gains a Sprint 6 "Grounded chat" subsection.
- [ ] Sprint 6 report: `sprints/sprint_6/sprint_6_report.md`.
- [ ] Bug-swatting log + tech-debt log updated with anything surfaced.
- [ ] Commit + push `sprints/sprint-6`; user reviews on the branch (same workflow as 5b / 5c).

---

## Definition of Done

- [ ] Ask a question on a workspace with ingested PDFs → grounded answer cites ≥ 1 note / entity / episode when corpus is relevant (**SM-6** directional).
- [ ] Empty corpus → explicit refusal (**US-8.9**).
- [ ] Stop button cancels within 1s (**US-8.8** AC-2). Test pattern mirrors Sprint 5b's `_classify_cancel_reason`.
- [ ] Retrieval inspector data identical when reopened (**US-8.4** AC-3) — `RetrievalRecord` is the source of truth.
- [ ] Pipeline + web typechecks clean; new chat tests pass on the host runner.
- [ ] `JobLogConsole` drawer also shows chat-turn events when expanded (free win from event reuse).

## Out of scope (deferred)

- **Sprint 6b — GraphRAG vs regular RAG evaluation.** Add a hidden `retrieval_mode` toggle on each session and turn (`graph` | `rag`); build a small canned question set; compute retrieval precision / recall and answer-citation overlap. Sprint 6 just persists `retrieval_mode='graph'` on every turn so the field is ready when 6b lands.
- **Sprint 7** — Chat Home (session list), Chat Drawer in the three-panel layout, scope-picker UX, regeneration with `is_active_alternate`, persistent share visibility, external Neo4j / AGE persistence writer.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Cohere citation `document_ids` opaque or unstable across model versions | Round-trip fixtures pinned to the SDK version; adapter test reproduces a known input/output pair |
| Token budget blowups with note + entity + episode documents | Per-turn doc-token cap configurable per workspace; smallest-first ordering |
| Retrieval misses obvious entities | Use Sprint 5c's typed-entity recall (typed labels improve Graphiti's hybrid search); validated on Oil & Gas PDF: 181 entities / 58 edges, real type diversity |
| Empty stream from Cohere chat | Reuse BUG-009 fallback pattern: detect empty buffer, retry `stream=False`, surface a `warning`-level log event into the drawer |
| Session orphans on workspace delete | FK CASCADE per `datamodel.md`; covered by migration 0009 |
| TD-010 edge-timestamp 400 storm still firing during retrieval | Retrieval uses Graphiti `search()` not `add_episode`, so the timestamp extractor is not on the chat hot path — no fix required for Sprint 6 |

## Sprint review (fill at end)

### Demo readiness

### Gaps / issues

### Next sprint prep
