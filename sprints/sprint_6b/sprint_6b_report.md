# Sprint 6b report

**Status**: Implementation complete on branch `sprints/sprint-6b`.

**Build**: pipeline suite is 87 passed / 14 skipped, including 19 new
Sprint 6b tests (`test_chat_intent.py`,
`test_chat_retrieval_boundaries.py`, `test_eval_scoring.py`). Web
`tsc --noEmit` is clean.

**Migrations to apply on review**: `0010_retrieval_eval_indexes`.

**Container rebuild required**: Postgres image (now
`pgvector/pgvector:pg16`, same data layout as `postgres:16-alpine`),
pipeline + worker (new pgvector/pyyaml deps, new retrieval modules),
web (new chat tabs + compare panel + retrieval-strategy selector).

## Goal

Build the GraphRAG-vs-Naive-RAG evaluation harness, ship the
deterministic graph-traversal handlers tracked as **TD-015**, and let
every user — not just admins — compare retrieval strategies inside
the regular Chat interface.

## Shipped

| Phase | Area | Summary |
| ----- | ---- | ------- |
| **1** | Data | Postgres switched to `pgvector/pgvector:pg16`. New migration `0010_retrieval_eval_indexes` adds `retrieval_embeddings` with a strict `index_kind` discriminator (`raw_chunk`, `atomic_note`, `entity`, `relationship`, `graph_context`), a pgvector `vector(1536)` column, and an IVFFLAT ANN index. Same migration adds `chat_eval_runs` / `chat_eval_questions` / `chat_eval_results` for reproducible eval persistence. |
| **2** | Naive RAG | New [`retrieval_embeddings_repo.py`](../../apps/pipeline/app/retrieval_embeddings_repo.py), [`raw_chunk_index.py`](../../apps/pipeline/app/raw_chunk_index.py), and [`chat_retrieval_raw.py`](../../apps/pipeline/app/chat_retrieval_raw.py). The Naive RAG retrieval strategy is the **control arm**: it embeds the query, searches `retrieval_embeddings WHERE index_kind='raw_chunk'`, and assembles ChatDocuments from raw PDF chunks. Pinned by [`test_chat_retrieval_boundaries.py`](../../apps/pipeline/tests/test_chat_retrieval_boundaries.py) so a future refactor can't sneak in zettelkasten / graph artifacts. |
| **2** | Strategy router | `chat_turn._retrieve` is now a thin dispatcher that reads `model_settings.retrieval_mode` and routes to [`chat_retrieval_raw`](../../apps/pipeline/app/chat_retrieval_raw.py), [`chat_retrieval_graph`](../../apps/pipeline/app/chat_retrieval_graph.py), or [`chat_retrieval_hybrid`](../../apps/pipeline/app/chat_retrieval_hybrid.py). Each strategy returns a stable `retrieval_strategy` string so `retrieval_records.retrieval_strategy` reflects exactly what the eval saw (`rag_raw_chunk_v1`, `graph_graphiti_context_v1`, `hybrid_typed_entity_v1`, `hybrid_path_v1`, `hybrid_vector_v1`). |
| **3** | TD-015 handlers | New [`chat_intent.py`](../../apps/pipeline/app/chat_intent.py) classifies each query into `aggregation` / `multi_hop` / `vector` / `refusal_or_unknown` and extracts entity-type + mentioned-entity slots from the workspace's typed taxonomy. New [`chat_handler_typed.py`](../../apps/pipeline/app/chat_handler_typed.py) answers "how many X" / "list all Y" by running a deterministic `SELECT` over `entities`. New [`chat_handler_path.py`](../../apps/pipeline/app/chat_handler_path.py) answers "how is A related to B" via depth-bounded BFS over `relationships` (default `max_depth=3`, `max_paths=5`). |
| **4** | Eval suite | New [`apps/pipeline/app/eval/`](../../apps/pipeline/app/eval/) folder containing the canned dataset ([`oil_gas_v1.yaml`](../../apps/pipeline/app/eval/datasets/oil_gas_v1.yaml), 16 questions in 4 categories), the headless runner ([`runner.py`](../../apps/pipeline/app/eval/runner.py), CLI: `python -m app.eval.runner --workspace-id <uuid>`), and the scorer ([`scoring.py`](../../apps/pipeline/app/eval/scoring.py)) which computes pattern-match, citation recall, refusal precision, and mode + category roll-ups. Eval runs persist to the `chat_eval_*` tables. |
| **4** | Internal routes | New [`internal_eval.py`](../../apps/pipeline/app/internal_eval.py): backfill the Naive RAG raw-chunk index, kick off an eval run in the background, list and fetch eval runs. Wired into `main.py`. |
| **5** | UI | `chat-panel.tsx` now ships a user-facing `RetrievalModeSelector` segment control (Naive RAG / GraphRAG / Hybrid) with inline tagline + helper text describing what each mode uses. The mode is locked once a session has turns. New [`chat-compare-panel.tsx`](../../apps/web/src/components/chat-compare-panel.tsx) renders three streaming answer cards side by side. New [`chat-tabs-client.tsx`](../../apps/web/src/components/chat-tabs-client.tsx) gives the `/chat` route a `Chat` / `Compare strategies` tab pair — both visible to every user. |
| **5** | Web proxies | New `retrieval-index/status` + `retrieval-index/backfill` Next.js proxies so the comparison UI can pre-warm the Naive RAG index from the browser when it's empty. |
| **6** | Tests | 19 new pipeline tests pin the intent router, the Naive RAG isolation contract, the dispatcher routing, and the eval scoring rubric. Full suite is 87 passed / 14 skipped. |

## Definition-of-done check

- [x] **Eval suite is reproducible** — pinned by dataset YAML, deterministic scoring, and persisted rows. Re-running the same dataset against the same workspace produces the same rows in `chat_eval_*` (modulo Cohere stochasticity in the generation step).
- [x] **All three retrieval modes reachable** — `rag`, `graph`, `hybrid` are selectable per session via the UI and per run via the eval CLI.
- [x] **Aggregation gap demonstrated** — `hybrid` mode dispatches to the typed-entity handler when the intent router fires; the same workspace question that returned "3" under Sprint 6 GraphRAG now returns the structured count + full named list.
- [x] **Multi-hop gap demonstrated** — `hybrid` mode runs BFS over `relationships`; other modes do not.
- [x] **Strict Naive RAG boundary** — `test_chat_retrieval_boundaries.py::test_naive_rag_source_does_not_import_graph_artifacts` scans `chat_retrieval_raw.py` for forbidden imports and call patterns. The only allowed `graphiti_factory` import is the API-key decoder, explicitly documented.
- [x] **Comparison UI for every user** — `Compare strategies` tab is part of the regular `/chat` surface, not behind any admin gate.
- [x] **Pipeline + boundary + scoring tests green** — 19 new tests pass; pre-existing 65 chat tests still pass.

## Files

### Migrations
- [`apps/migrations/alembic/versions/0010_retrieval_eval_indexes.py`](../../apps/migrations/alembic/versions/0010_retrieval_eval_indexes.py)

### New pipeline modules
- [`apps/pipeline/app/retrieval_embeddings_repo.py`](../../apps/pipeline/app/retrieval_embeddings_repo.py)
- [`apps/pipeline/app/raw_chunk_index.py`](../../apps/pipeline/app/raw_chunk_index.py)
- [`apps/pipeline/app/chat_retrieval_raw.py`](../../apps/pipeline/app/chat_retrieval_raw.py)
- [`apps/pipeline/app/chat_retrieval_graph.py`](../../apps/pipeline/app/chat_retrieval_graph.py)
- [`apps/pipeline/app/chat_retrieval_hybrid.py`](../../apps/pipeline/app/chat_retrieval_hybrid.py)
- [`apps/pipeline/app/chat_intent.py`](../../apps/pipeline/app/chat_intent.py)
- [`apps/pipeline/app/chat_handler_typed.py`](../../apps/pipeline/app/chat_handler_typed.py)
- [`apps/pipeline/app/chat_handler_path.py`](../../apps/pipeline/app/chat_handler_path.py)
- [`apps/pipeline/app/internal_eval.py`](../../apps/pipeline/app/internal_eval.py)
- [`apps/pipeline/app/eval/`](../../apps/pipeline/app/eval/) (package — runner, scoring, dataset, README)

### Modified pipeline modules
- [`apps/pipeline/app/chat_turn.py`](../../apps/pipeline/app/chat_turn.py) — `_retrieve` is now a dispatcher; reads `model_settings.retrieval_mode`; logs strategy in the drawer.
- [`apps/pipeline/app/main.py`](../../apps/pipeline/app/main.py) — registers `internal_eval_router`.
- [`apps/pipeline/requirements.txt`](../../apps/pipeline/requirements.txt) — adds `pgvector` and `pyyaml`.

### New web routes
- `apps/web/src/app/api/v1/workspaces/[workspaceId]/retrieval-index/status/route.ts`
- `apps/web/src/app/api/v1/workspaces/[workspaceId]/retrieval-index/backfill/route.ts`

### New web components
- `apps/web/src/components/chat-compare-panel.tsx`
- `apps/web/src/components/chat-tabs-client.tsx`

### Modified web modules
- `apps/web/src/app/(workspace)/chat/page.tsx` — now mounts `<ChatTabsClient />`.
- `apps/web/src/components/chat-panel.tsx` — adds `RetrievalModeSelector` and threads `model_settings.retrieval_mode` through on session create.

### Infra
- `docker-compose.yml` — `postgres` image switched to `pgvector/pgvector:pg16`.

### Tests (19 new)
- `apps/pipeline/tests/test_chat_intent.py`
- `apps/pipeline/tests/test_chat_retrieval_boundaries.py`
- `apps/pipeline/tests/test_eval_scoring.py`

## How to deploy

```bash
# 1. Pull the new Postgres image and recreate the container (pgdata
#    volume is preserved — same on-disk layout)
docker compose up -d --force-recreate postgres

# 2. Apply the new migration
docker compose run --rm migrate

# 3. Rebuild pipeline + worker + web
docker compose up -d --build pipeline worker web

# 4. Pre-warm the Naive RAG raw-chunk index for your workspace so the
#    first 'rag' question doesn't time out on the embedding pass:
curl -X POST \
  "http://localhost:3000/api/v1/workspaces/<workspace-uuid>/retrieval-index/backfill" \
  -H "Content-Type: application/json" \
  -d '{}'

# 5. (Optional) Run the canned eval CLI:
docker compose exec pipeline \
  python -m app.eval.runner \
    --workspace-id <workspace-uuid> \
    --modes rag,graph,hybrid \
    --notes "Sprint 6b dry run"
```

## Known follow-ups

- **Asymmetric embed input types** — the embedder currently uses
  `input_type='search_document'` for both indexing and query. Cohere
  recommends `search_query` for queries. Tracked as a TD; small change,
  low risk.
- **Dataset expansion** — `oil_gas_v1.yaml` ships 16 questions to keep
  the sprint shippable. Adding more questions per category is the
  cheapest way to make the eval more statistically meaningful.
- **LLM-as-judge scoring** — Sprint 6b is regex / substring only. A
  follow-up sprint can layer in semantic scoring once we have a
  larger dataset to calibrate against.
- **`chat_eval_results` cross-link** — eval rows currently store
  answer text + score summary but do not foreign-key to live
  `chat_messages` / `retrieval_records` (those are scoped to chat
  sessions and the eval runs headlessly). A follow-up could persist
  per-eval mini sessions so the existing chat-turn retrieval
  inspector covers eval runs too.
- **Production retrieval refactor** — the new strategy modules
  duplicate small helpers (`_attr`, `_str_list`, `_parse_iso`). After
  the dust settles a quick consolidation pass is worth it.

## Risks accepted / mitigated

| Risk | Outcome |
|---|---|
| pgvector image swap breaks existing data | Same `pgdata` volume, same Postgres 16 base; verified migration ran cleanly on the existing DB. |
| Naive RAG accidentally uses graph artifacts | Pinned by static-source boundary test. |
| Intent router false positives | Conservative heuristics; multi-hop requires two extracted entity mentions before firing; falls through to vector mode otherwise. |
| Big workspaces blow the eval budget | Headless runner serializes per (question, mode) pair; the CLI prints per-question progress so an operator can ctrl-C at will. |
| Mode switch mid-session confuses users | Selector locks once the session has turns. New mode → new session. |
