# Sprint 6b — GraphRAG vs Naive RAG: eval harness + deterministic traversal

**Branch (planned)**: `sprints/sprint-6b`
**Duration**: 1.5–2 weeks
**Goal**: Pin **SM-6** ("Median weekly active user asks ≥ 5 chat questions per week, and ≥ 80% of those answers receive at least one citation") with a quantitative answer to the question Johnny keeps asking out loud: *"what's the point of building a graph if we don't traverse it?"* Sprint 6 left chat at vanilla GraphRAG = "vector retrieval over a graph-shaped index." Sprint 6b ships (a) the eval harness that lets us measure that vs naive RAG and vs a graph-traversal variant, and (b) the **TD-015 traversal handlers** that the eval is meant to motivate.

## Inputs

- Sprint 6's grounded-chat pipeline (`chat_turn`, `cohere_chat`, `chat_repo`, `retrieval_repo`, `chat_citations`).
- `chat_messages.retrieval_mode` column already ships defaulting to `'graph'` (migration `0009_chat_tables`). The check constraint accepts `graph | rag | hybrid` so 6b adds the alternate paths without another migration.
- Graph-context grounding document (BUG-013 partial mitigation). 6b will measure how much *additional* lift the typed-traversal handlers buy over that baseline.
- TD-015 in [`sprints/tech_debt.md`](../tech_debt.md) — full description of the structured-query routing work.

## Outputs

- A reproducible eval suite under `apps/pipeline/eval/` plus user-facing Chat UI controls that let any user select retrieval strategy and compare GraphRAG vs Naive RAG vs Hybrid answers side-by-side.
- Three production retrieval modes wired up:
  - `rag` (**Naive RAG baseline**): embed and retrieve from the original parsed document chunks / episodes only. It must **not** use zettelkasten atomic notes, extracted entities, relationships, graph-context documents, or graph traversal. This is the control arm.
  - `graph` (**current GraphRAG baseline**): Sprint 6 retrieval path — Graphiti hybrid search over the graph-shaped index + zettelkasten-derived notes/entities/relationships + graph-context document.
  - `hybrid` (**GraphRAG with deterministic traversal**): graph traversal handlers + supporting raw-chunk evidence where helpful.
- TD-015 intent router + typed-entity handler + multi-hop traversal handler.

## Dependencies

- Sprint 6 merged into `main` (done — tag `sprint-6`).
- BUG-013 mitigation shipped in Sprint 6 (done — graph-context grounding document).

---

## Tasks (placeholder — refine during planning cycle)

> The user will refine this section during the dedicated 6b planning cycle. Below is the working outline so planning has a structured starting point, not a blank page.

### Phase 0 — Paperwork

- [x] Branch `sprints/sprint-6b` off `main`.
- [x] Confirm `specs/apis.md` Chat section already documents `chat_messages.retrieval_mode` and the graph-context grounding document (Sprint 6 spec sync covered this).

### Phase 1 — Migration `0010_retrieval_eval_indexes`

- [x] Switched Postgres image to `pgvector/pgvector:pg16` (drop-in for the existing `pgdata` volume).
- [x] New migration creates `retrieval_embeddings` with a strict `index_kind` discriminator (`raw_chunk` | `atomic_note` | `entity` | `relationship` | `graph_context`) plus a pgvector `vector(1536)` column and IVFFLAT ANN index.
- [x] Same migration creates `chat_eval_runs` / `chat_eval_questions` / `chat_eval_results` so eval runs are reproducible and historical results survive dataset edits.

### Phase 2 — Naive RAG raw-chunk index + retrieval strategies

- [x] `apps/pipeline/app/retrieval_embeddings_repo.py` — sync psycopg repo with pgvector adapter, upsert / search / count by `index_kind`.
- [x] `apps/pipeline/app/raw_chunk_index.py` — backfill PDF chunks (`episodes` rows of kind `pdf_chunk`) into the index; idempotent.
- [x] `apps/pipeline/app/chat_retrieval_raw.py` — Naive RAG retrieval strategy. Pinned by `test_chat_retrieval_boundaries.py` to never touch atomic notes / entities / relationships / graph context / Graphiti.
- [x] `apps/pipeline/app/chat_retrieval_graph.py` — Sprint 6 GraphRAG path factored out.
- [x] `apps/pipeline/app/chat_retrieval_hybrid.py` — Hybrid = deterministic handler + graph-strategy supporting evidence.
- [x] `chat_turn._retrieve` is now a thin dispatcher; tagged each strategy with a stable `retrieval_strategy` string (e.g. `rag_raw_chunk_v1`, `graph_graphiti_context_v1`, `hybrid_typed_entity_v1`, `hybrid_path_v1`, `hybrid_vector_v1`).
- [x] `model_settings.retrieval_mode` from the session drives the dispatcher.

### Phase 3 — TD-015 traversal handlers

- [x] `apps/pipeline/app/chat_intent.py` — deterministic rule-based intent router with slot extraction (`entity_types`, `mentioned_entities`). Pinned by `test_chat_intent.py`.
- [x] `apps/pipeline/app/chat_handler_typed.py` — "how many X" / "list all Y" answered by a structured `SELECT` over `entities`, rendered as a `ChatDocument` with authoritative counts + full names (capped at 500 per type).
- [x] `apps/pipeline/app/chat_handler_path.py` — depth-bounded BFS over `relationships`, rendered as `A -[REL]-> B -[REL]-> C` plus the supporting edge facts. Default `max_depth=3`, `max_paths=5`.
- [x] `chat_retrieval_hybrid` composes handlers + graph supporting evidence in one bundle.

### Phase 4 — Eval dataset + runner + scoring

- [x] `apps/pipeline/app/eval/datasets/oil_gas_v1.yaml` — canned dataset with 16 questions across `aggregation`, `multi_hop`, `vector`, and `refusal` categories (4 each).
- [x] `apps/pipeline/app/eval/scoring.py` — pattern-match, citation recall, refusal precision; mode + category roll-ups. Pinned by `test_eval_scoring.py`.
- [x] `apps/pipeline/app/eval/runner.py` — headless runner that exercises retrieval + Cohere chat in-process (bypasses arq for speed), persists eval rows, prints a per-question summary and a final JSON roll-up. Also installable as `python -m app.eval.runner --workspace-id <uuid>`.
- [x] `apps/pipeline/app/internal_eval.py` — internal endpoints for raw-chunk backfill, eval-run lifecycle, and listing past runs.

### Phase 5 — Chat strategy comparison UI

- [x] User-facing `RetrievalModeSelector` segment control inside `chat-panel.tsx`. Each option carries an inline tagline + helper text describing the boundary (Naive RAG = raw chunks only; GraphRAG = zettelkasten + graph context; Hybrid = deterministic traversal + supporting evidence). Locks once the session has any turns.
- [x] New `chat-compare-panel.tsx` — side-by-side comparison surface. One textbox; submit fires three parallel sessions (one per mode), renders three streaming answer cards with citation counts, latency, token usage, and status badges.
- [x] New `chat-tabs-client.tsx` — tabs over the chat page (`Chat` / `Compare strategies`). Both views ship in the regular chat surface for every user — not behind any admin gate.
- [x] Web proxies for `retrieval-index/status` + `retrieval-index/backfill` so the comparison UI can pre-warm the Naive RAG index when needed.

### Phase 6 — Tests + closeout

- [x] `apps/pipeline/tests/test_chat_intent.py` — pins the intent router heuristics.
- [x] `apps/pipeline/tests/test_chat_retrieval_boundaries.py` — pins the Naive RAG isolation contract + the dispatch routing.
- [x] `apps/pipeline/tests/test_eval_scoring.py` — pins the scoring rubric.
- [x] Full pipeline suite green (87 passed / 14 skipped), web `tsc --noEmit` clean.
- [x] Sprint 6b report: `sprints/sprint_6b/sprint_6b_report.md`.
- [ ] Tag `sprint-6b` after PR merge.

## Definition of Done

- [x] Eval suite is reproducible: same dataset + same code → same persisted rows in `chat_eval_runs` / `chat_eval_questions` / `chat_eval_results`.
- [x] All three retrieval modes (`rag`, `graph`, `hybrid`) reachable in production code and selectable per session.
- [x] Aggregation questions: `hybrid` mode answers deterministically via the typed-entity handler; `graph` mode uses the graph-context doc; `rag` is forbidden from using either.
- [x] Multi-hop questions: `hybrid` mode runs depth-bounded BFS over `relationships`; other modes are allowed to fail.
- [x] Side-by-side comparison view ships inside the Chat interface for all users.
- [x] Pipeline tests + boundary tests + scoring tests all green.

## Risks

| Risk | Mitigation |
|---|---|
| Hand-curated dataset is too small to make claims | Aim for ≥ 30 questions; document as v1, expand in 6c |
| Intent router false positives route real questions to wrong handler | Conservative thresholds + fall-through to vector retrieval; pinned by intent tests |
| Multi-hop path queries are slow on big graphs | Hard depth cap (3), node budget cap, time budget (5s) per path query; surface degradation in the drawer |
| LangExtract / Graphiti version churn | Pin versions per Sprint 5c convention; eval runs CI-friendly so regressions are caught |

## Out of scope (deferred)

- Advanced eval-run management beyond the Chat comparison surface — export/history polish can move to Sprint 7.
- Regeneration + `is_active_alternate` UI — Sprint 7.
- Cross-workspace eval datasets — 6c.
