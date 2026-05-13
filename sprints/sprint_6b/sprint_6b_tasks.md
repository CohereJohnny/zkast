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

- A reproducible eval suite under `apps/pipeline/eval/` plus a UI surface (likely an admin-gated page) that runs the suite, shows per-question + aggregate metrics, and lets the user diff GraphRAG vs Naive RAG vs Hybrid answers side-by-side.
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

- [ ] Branch `sprints/sprint-6b` off `main` (already created).
- [ ] Confirm `specs/apis.md` Chat section already documents `chat_messages.retrieval_mode` and the graph-context grounding document (Sprint 6 spec sync covered this).

### Phase 1 — Typed-question taxonomy + canned dataset

- [ ] Define question categories in `apps/pipeline/eval/taxonomy.py`:
  - **Vector-friendly** ("What does Deloitte say about predictive algorithms?"): vanilla RAG can win.
  - **Aggregation** ("How many Locations? List all Standards. Count Organizations by sector."): graph-context doc partially wins today; deterministic traversal should dominate.
  - **Multi-hop** ("How does Deloitte connect to Probabilistic Safety Assessment? Path from X to Y?"): only traversal can answer correctly.
  - **Counterfactual / refusal** ("What's the population of Canada per this document?"): all modes should refuse.
- [ ] Build a hand-curated canned set (~30 questions, ~10 per category × 3 expected answers each) keyed against the Oil & Gas workspace as the canonical fixture. Store under `apps/pipeline/eval/datasets/oil_gas_v1.yaml`.
- [ ] Document the labelling protocol (expected entity ids cited, expected answer regex, refusal-OK flag) in `apps/pipeline/eval/README.md`.

### Phase 2 — Retrieval-mode plumbing

- [ ] `chat_turn` reads `chat_messages.retrieval_mode` (or `session.model_settings.retrieval_mode`) and dispatches to one of three retrieval branches:
  - `rag`: skip Graphiti and skip zettelkasten. Embed the query against the original parsed document chunks / `episodes` produced by PDF parsing, then build Cohere documents from the top-K raw chunks with page provenance. This mode is intentionally "dumber" so it remains a fair Naive RAG baseline.
  - `graph`: today's Sprint 6 path (Graphiti hybrid search over zettelkasten-derived entities/relationships + graph-context doc).
  - `hybrid`: graph-traversal handlers (Phase 3) + supporting raw-chunk evidence from `rag`.
- [ ] Per-mode retrieval-strategy tag stored on `retrieval_records.retrieval_strategy` so the eval can group by it.
- [ ] Web side: small admin/eval-only `retrieval_mode` picker in `ChatScopePicker` behind a feature flag (hidden in default UI per `model_settings.retrieval_mode`).

### Phase 3 — TD-015 traversal handlers

- [ ] **Intent router** (`apps/pipeline/app/chat_intent.py`): heuristic + LLM-backed classifier that detects `aggregation`, `multi_hop`, `vector` intent from the query. Falls through to `vector` on uncertainty. Pinned by unit tests against the canned dataset.
- [ ] **Typed-entity handler** (`apps/pipeline/app/chat_handler_typed.py`): given an `aggregation` intent + a recognized type ("Location", "Standard"), runs a deterministic `SELECT … WHERE workspace_id = ? AND type = ?` against Postgres and returns the entities as a structured `ChatDocument`. Handles "how many", "list all", "count by".
- [ ] **Multi-hop handler** (`apps/pipeline/app/chat_handler_path.py`): given a `multi_hop` intent + two recognized entities, runs a depth-bounded path query via Graphiti's traversal API (or a fallback Cypher / SQL recursion over `relationships`) and returns the path as a structured `ChatDocument`. Pin path length (default 3).
- [ ] Compose into the existing `_retrieve` so `hybrid` mode returns the deterministic answer **plus** vector evidence in the same bundle.

### Phase 4 — Eval runner + scoring

- [ ] `apps/pipeline/eval/runner.py`: pytest-style fixture that iterates the canned dataset, calls `chat_turn.run_chat_turn` once per `(question, mode)` pair, persists `(eval_run_id, question_id, mode, answer, citations, retrieval_record_id)` rows in a new `chat_eval_runs` table.
- [ ] Scoring rubric:
  - **Citation recall** — fraction of `expected_entity_ids` that appear in `chat_citations.sources`.
  - **Answer correctness** — regex / substring match against `expected_answer_patterns`.
  - **Refusal precision** — for questions flagged `refusal_expected=true`, mode must refuse; for others, it must not.
  - **Retrieval latency** — `retrieval_records.created_at - chat_messages.created_at`.
  - **Tokens consumed** — `tokens_in + tokens_out` from `chat_messages`.
- [ ] CSV / JSON output + a simple HTML report dropped into `apps/pipeline/eval/reports/<run_id>/`.

### Phase 5 — UI

- [ ] Admin-gated `/admin/eval` page that lists eval runs, lets the user kick off a new one, and renders the side-by-side per-question diff: question + expected answer + RAG answer + Graph answer + Hybrid answer, with the recall/correctness/latency cells colored green/red.
- [ ] One-click "re-run this question" affordance so the user can iterate on the handlers without restarting the whole suite.

### Phase 6 — Closeout

- [ ] Sprint 6b report with the headline numbers (recall/correctness/latency per mode, per category).
- [ ] Update `README.md` Sprint status row.
- [ ] Tag `sprint-6b`, merge PR, archive `sprints/sprint_6b/` if archive convention re-instituted.

## Definition of Done

- [ ] Eval suite is reproducible: same dataset + same code → same metrics (deterministic seeds where possible).
- [ ] All three retrieval modes (`rag`, `graph`, `hybrid`) reachable in production code and selectable per session.
- [ ] Aggregation questions: `hybrid` mode answers correctly with deterministic counts/lists; `graph` mode hits the graph-context doc; `rag` mode is allowed to fail. Quantified delta in the report.
- [ ] Multi-hop questions: `hybrid` mode returns correct paths; `rag` and `graph` modes are allowed to fail. Quantified delta in the report.
- [ ] Side-by-side comparison view ships behind an admin gate.
- [ ] Pipeline tests (existing + new intent / typed-entity / multi-hop tests) all green.

## Risks

| Risk | Mitigation |
|---|---|
| Hand-curated dataset is too small to make claims | Aim for ≥ 30 questions; document as v1, expand in 6c |
| Intent router false positives route real questions to wrong handler | Conservative thresholds + fall-through to vector retrieval; pinned by intent tests |
| Multi-hop path queries are slow on big graphs | Hard depth cap (3), node budget cap, time budget (5s) per path query; surface degradation in the drawer |
| LangExtract / Graphiti version churn | Pin versions per Sprint 5c convention; eval runs CI-friendly so regressions are caught |

## Out of scope (deferred)

- Public-facing retrieval-mode picker on the user-facing ChatScopePicker — admin/eval-gated in 6b; user-facing in Sprint 7.
- Regeneration + `is_active_alternate` UI — Sprint 7.
- Cross-workspace eval datasets — 6c.
