# Sprint B Tasks — A-MEM Embeddings And Agent UI

**Branch**: `sprints/sprint-b`
**Status**: Complete (implementation on `sprints/sprint-b`)
**Primary spec**: [`specs/openspecs/north-agents-amem.md`](../../specs/openspecs/north-agents-amem.md) — **FR-7**, **FR-9** (agent-scoped retrieval inputs; not FR-8 dreaming)
**Depends on**: Sprint A ([`sprint_a_report.md`](../sprint-a/sprint_a_report.md)) — North import, `agent_id` on documents/episodes/notes

## Goals

- Make **A-MEM enrichment** reliable and observable for **North-derived** atomic notes (keywords, context, optional tag augmentation) without mutating note bodies or source text.
- Ensure **agent-scoped note embeddings** (`note_zettel`, `note_amem`) exist for retrieval and can be **backfilled** for notes created before this sprint.
- Improve **agent-scoped workspace UI** (agent detail stats, pickers, graph/notes filters) so mixed PDF + North workspaces stay navigable.
- Prepare clean inputs for Sprint C (dreaming jobs, link isolation hardening, eval modes) — **do not** implement dreaming audit UI or North-history eval in this sprint.

## Baseline (already on `main` — verify, don’t re-build)

Sprint 6c + Sprint A shipped substantial scaffolding. Sprint B **hardens and completes** these paths:

| Area | Existing modules / behavior |
| ---- | --------------------------- |
| Schema | Migration [`0011_north_agents_amem.py`](../../apps/migrations/alembic/versions/0011_north_agents_amem.py): `memory_context`, `memory_keywords`, `evolution_history`, `dreaming_touched_at` on `atomic_notes`; `agent_id` on notes/episodes/documents; `retrieval_embeddings.agent_id` |
| Enrichment | [`amem_enrich.py`](../../apps/pipeline/app/amem_enrich.py) — batch LLM JSON → `patch_note_derivations` |
| Ingestion wire-up | [`tasks.py`](../../apps/pipeline/app/tasks.py) — after `generating_notes`: zettel embed → enrich → amem embed; `agent_scope` from episode `agent_id` |
| Note embeddings | [`note_embedding_index.py`](../../apps/pipeline/app/note_embedding_index.py) — `INDEX_KIND_NOTE_ZETTEL` / `INDEX_KIND_NOTE_AMEM` |
| Retrieval | [`chat_retrieval_notes_vector.py`](../../apps/pipeline/app/chat_retrieval_notes_vector.py) — `retrieve_amem` searches `note_amem` with optional `agent_id` |
| Notes API | [`notes_repo.py`](../../apps/pipeline/app/notes_repo.py) — list filter `agent_id`; `patch_note_derivations` |
| Notes UI | [`notes-page-client.tsx`](../../apps/web/src/components/notes-page-client.tsx) — `agent_id` query param; raw UUID filter in [`notes-list.tsx`](../../apps/web/src/components/notes-list.tsx) |
| Note detail | [`note-detail.tsx`](../../apps/web/src/components/note-detail.tsx) — displays A-MEM fields when present |
| Agents | [`agents-panel.tsx`](../../apps/web/src/components/agents-panel.tsx), [`agent-detail-panel.tsx`](../../apps/web/src/components/agent-detail-panel.tsx) — sync, import, conversation preview |
| Graph source | [`source-picker.tsx`](../../apps/web/src/components/filters/source-picker.tsx) — PDF + North documents by `document_id` (not agent-wide) |
| Raw index only | [`internal_eval.py`](../../apps/pipeline/app/internal_eval.py) — `retrieval-index/status` + `backfill` for **raw_chunk** only |

**Explicitly out of scope (Sprint C / D):** `run_dreaming_job` product UX, `dream_jobs` / mutation audit surfaces, cross-agent link enforcement tests, North-history eval dataset, chat retrieval-mode matrix — even though [`dreaming.py`](../../apps/pipeline/app/dreaming.py) and a **Dream** button exist today.

---

## Tasks

### Phase 0 — Sprint setup

- [x] Branch `sprints/sprint-b` from updated `main` after Sprint A merge (`235d602`).
- [ ] Confirm North import produces `atomic_notes.agent_id` matching the importing agent (spot-check one conversation import).
- [ ] Confirm PDF ingestion still produces notes with `agent_id` **null** and completes zettel embed path.
- [x] Review [`north-agents-amem.md`](../../specs/openspecs/north-agents-amem.md) FR-7 and FR-9; list any spec gaps in Progress below.
- [x] Keep progress notes under each phase as work proceeds.

**Progress:**

---

### Phase 1 — A-MEM enrichment (hardening)

**Target:** FR-7, NFR-2 — derived fields only; failures visible in job log.

- [x] **Scope enrichment to North-derived notes** — run `enrich_notes_amem_batch` only when `agent_scope` is set (or note rows have non-null `agent_id`); skip for PDF-only runs to save tokens and match spec intent.
- [x] **Tag augmentation** — extend enrichment prompt + `patch_note_derivations` to merge LLM-proposed tags into existing `tags` (dedupe, lowercase) without replacing user tags.
- [x] **Immutability guard** — assert enrichment never updates `title` / `body`; add test that compares note body hash before/after enrich.
- [x] **Fix `dreaming_touched_at` semantics** — enrichment should **not** set `dreaming_touched_at` (reserve for Sprint C dreaming); split `patch_note_derivations` vs dreaming update helper if needed.
- [x] **Job telemetry** — on enrich start/complete/partial failure, emit `record_log` / `record_metric` on the ingestion `job_id` (notes stage); surface per-note skip reasons when LLM returns malformed items.
- [x] **Resilience** — cap batch size; on total LLM failure, log warning + metric but do not fail entire ingestion run (notes already created).
- [x] **Optional:** workspace `pipeline_settings` flag `amem_enrich_enabled` (default true for North) for operator kill-switch.

**Key files:** [`amem_enrich.py`](../../apps/pipeline/app/amem_enrich.py), [`tasks.py`](../../apps/pipeline/app/tasks.py), [`notes_repo.py`](../../apps/pipeline/app/notes_repo.py)

**Progress:**

---

### Phase 2 — Note embeddings and backfill

**Target:** FR-9 retrieval inputs — `note_zettel` + `note_amem` with `agent_id` on index rows.

- [x] **Extend retrieval-index status** — include counts for `note_zettel`, `note_amem`, and `raw_chunk` via `retrieval_embeddings_repo.count_by_kind`; optional breakdown by `agent_id` for North rows.
- [x] **Note embedding backfill** — new pipeline helper (e.g. `note_embedding_index.backfill_notes`) that:
  - selects notes missing `note_zettel` / `note_amem` rows (or stale after enrich);
  - runs zettel embed for all notes, amem embed only when `memory_context` or `memory_keywords` present;
  - passes `agent_id` from `atomic_notes.agent_id`.
- [x] **Wire internal route** — extend `POST .../retrieval-index/backfill` body with `kinds: ["raw_chunk" | "note_zettel" | "note_amem"]` and optional `agent_id` filter; keep raw_chunk behavior unchanged.
- [x] **Web proxy** — update [`retrieval-index/backfill/route.ts`](../../apps/web/src/app/api/v1/workspaces/[workspaceId]/retrieval-index/backfill/route.ts) and Diagnostics (or Settings) to trigger note backfill and show per-kind counts.
- [x] **Ingestion ordering** — verify order remains: create notes → zettel embed → enrich → amem embed (re-embed amem only after enrich writes keywords/context).
- [x] **Idempotency** — backfill skips already-indexed `source_id` per kind using `list_indexed_source_ids`.

**Key files:** [`note_embedding_index.py`](../../apps/pipeline/app/note_embedding_index.py), [`internal_eval.py`](../../apps/pipeline/app/internal_eval.py), [`retrieval_embeddings_repo.py`](../../apps/pipeline/app/retrieval_embeddings_repo.py)

**Progress:**

---

### Phase 3 — Agent-scoped UI

**Target:** Operator can see agent memory footprint and filter notes/graph without pasting UUIDs.

- [x] **Agent detail summary** — on [`agent-detail-panel.tsx`](../../apps/web/src/components/agent-detail-panel.tsx): show counts (imported conversations / documents, derived notes, optional `note_amem` index count); links:
  - **View notes** → `/notes?agentId={id}`
  - **View graph** → `/graph?agentId={id}` (once graph filter exists)
- [x] **`AgentPicker` component** — combobox over `GET .../north/agents` (display name + id); replace raw UUID field in [`notes-list.tsx`](../../apps/web/src/components/notes-list.tsx).
- [x] **Graph agent filter** — add `agent_id` query param to graph workspace URL; extend pipeline graph list/query ([`internal_graph.py`](../../apps/pipeline/app/internal_graph.py) or entity repo) to filter entities/edges/notes provenance by agent when set; add `AgentPicker` to [`graph-filter-bar.tsx`](../../apps/web/src/components/graph-filter-bar.tsx) (orthogonal to `SourcePicker` document filter).
- [x] **Agents list row actions** — quick links: Notes, Graph (scoped), Conversations (existing detail).
- [x] **Loading / empty / error** — consistent patterns on agent detail stats fetch and picker load failures.
- [x] **Do not expand Dream UX** — leave existing Dream button as-is; full job status belongs in Sprint C.

**Key files:** agent + notes + graph components above; may need small internal `GET .../north/agents/{id}/stats` if counts are expensive client-side.

**Progress:**

---

### Phase 4 — Mixed-agent boundaries

**Target:** PDF corpus remains visible workspace-wide; North scope is opt-in via agent filter.

- [x] **Notes default** — with no `agent_id` filter, list includes PDF notes (`agent_id` null) **and** all North notes (document current API behavior; add regression test).
- [x] **Notes scoped** — with `agent_id` set, list returns only notes for that agent (exclude null-agent PDF notes unless product decision: add explicit “include workspace PDFs” toggle — default **off**).
- [x] **Graph default** — no `agent_id`: unchanged full workspace graph (or document/source filters only).
- [x] **Graph scoped** — with `agent_id`: subgraph or filtered entity set tied to that agent’s episodes/documents (define truncation behavior in Progress).
- [x] **Chat scope (light touch)** — confirm chat session scope picker can pass `agent_id` where eval already supports it; full chat UX for agent scope is Sprint D unless trivial.

**Progress:**

---

### Phase 5 — Tests and verification

- [x] **`test_amem_enrich.py`** — mock LLM: output shape, body unchanged, keywords/context persisted, tags merged, no `dreaming_touched_at` on enrich-only path.
- [x] **`test_note_embedding_index.py`** — zettel/amem upsert sets `agent_id`; `_amem_text` includes context/keywords; backfill skips existing ids.
- [x] **`test_notes_agent_filter.py`** — list API with/without `agent_id`.
- [x] **`test_graph_agent_filter.py`** — graph endpoint respects `agent_id` when implemented.
- [x] **Regression** — existing North transcript + PDF ingestion tests still pass.
- [x] **Web** — `pnpm exec tsc --noEmit` and `pnpm run build` in `apps/web`.
- [ ] **Manual smoke** (operator):
  1. Import North conversation → notes show memory keywords/context in note detail.
  2. Diagnostics/backfill → `note_amem` count increases.
  3. Agent detail → counts + link to scoped notes/graph.
  4. PDF upload → notes created, no unnecessary A-MEM enrich (if scoped in Phase 1).

**Progress:**

---

## Definition of done

- [x] North-derived notes receive A-MEM enrichment (keywords, context, optional tags) with immutable note bodies and visible pipeline log lines on failure.
- [x] `retrieval_embeddings` contains `note_zettel` and `note_amem` rows with correct `agent_id`; backfill path exists for legacy notes.
- [x] Agent detail, notes, and graph surfaces support agent scope via pickers (not raw UUIDs).
- [x] Mixed PDF + North workspace: unscoped views show PDF content; scoped views isolate North agent artifacts.
- [x] Sprint B tests pass; web build green.
- [x] Sprint C/D scope unchanged (no dreaming audit UI, no eval dataset work).

---

## Sprint review

**Demo readiness:** A-MEM enrichment runs only for North imports; pipeline log lines on enrich; Diagnostics can backfill `note_zettel` / `note_amem`; agent detail shows counts and scoped Notes/Graph links; `AgentPicker` on Notes and Graph.

**Gaps / issues:** Manual smoke on live North tenant pending. Chat scope picker does not yet expose agent filter (eval API supports `agent_id`).

**Next steps:** Sprint C — dreaming jobs, link isolation, re-embed after dreaming ([`sprint_c_tasks.md`](../sprint-c/sprint_c_tasks.md)).

---

## Notes

- **Transparency:** Enrichment and embedding stages should log to `JobLogConsole` on Documents/Conversations routes (same principle as Sprint A).
- **Sprint 6c overlap:** Much schema and pipeline code landed early; Sprint B is primarily **correctness, scope, backfill, UI, and tests** — not greenfield schema work.
- Chat `amem_lite` retrieval already consumes `note_amem`; this sprint ensures indexes are populated and agent filters work upstream of Sprint C eval work.
