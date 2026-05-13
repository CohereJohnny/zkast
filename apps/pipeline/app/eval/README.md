# Sprint 6b — Chat Retrieval Eval Harness

This folder holds the Sprint 6b GraphRAG-vs-Naive-RAG eval harness.

## Goals

Quantify how different retrieval modes answer different question
shapes against a real workspace. Three modes are evaluated:

- **`rag` — Naive RAG baseline.** Vector retrieval over the original
  parsed PDF text chunks (`episodes`) only. No zettelkasten notes,
  no entities, no relationships, no graph context, no traversal.
  This is the control arm and is forbidden from using any
  zettelkasten / graph artifact.
- **`graph` — Sprint 6 GraphRAG baseline.** Graphiti hybrid search
  over the graph-shaped index plus the graph-context grounding
  document.
- **`hybrid` — GraphRAG with deterministic traversal.** Typed-entity
  aggregation and multi-hop path handlers (TD-015) plus supporting
  graph evidence.

## Files

| Path | Purpose |
|---|---|
| `datasets/oil_gas_v1.yaml` | Canned dataset (aggregation, multi-hop, vector, refusal). |
| `scoring.py` | Per-row scorers + aggregate roll-ups. |
| `runner.py` | Headless runner. Iterates the dataset across modes, persists `chat_eval_*` rows, returns a summary. |

## How to run

```
docker compose exec pipeline \
  python -m app.eval.runner \
    --workspace-id <workspace-uuid> \
    --modes rag,graph,hybrid \
    --notes "Sprint 6b dry run"
```

The runner will:

1. Backfill the Naive-RAG raw-chunk index lazily — but you should
   pre-warm it once via
   `POST /internal/v1/workspaces/{ws}/retrieval-index/backfill` so
   the first `rag` question doesn't time out on the embedding pass.
2. Iterate each question across the requested modes.
3. Persist `chat_eval_runs`, `chat_eval_questions`, `chat_eval_results`.
4. Print a one-line summary per (question, mode) and a final JSON
   roll-up.

## How to add a question

Edit `datasets/oil_gas_v1.yaml`. Each question carries:

- `key`               — stable identifier
- `category`          — `aggregation` / `multi_hop` / `vector` / `refusal`
- `question_text`     — user-facing prompt
- `expected_answer_patterns` — regex list; any match earns
  pattern-match credit
- `expected_entity_ids` — canonical entity names whose appearance in
  citations earns recall credit
- `refusal_expected`  — true when every mode must refuse
- `notes`             — human notes about why this question belongs
  to its category

## Out of scope this sprint

- LLM-as-judge scoring. Sprint 6b uses regex / substring scoring only.
- Cross-workspace datasets. The Oil & Gas fixture is the only one v1.
- Adversarial / red-team questions beyond the four refusal probes.
