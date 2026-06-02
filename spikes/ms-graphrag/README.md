# Spike: Microsoft GraphRAG as a parallel backend

Exploratory spike (throwaway-ish) to learn how to integrate **Microsoft GraphRAG**
as a parallel comparison backend in the composable harness, and to verify it runs
against our **Cohere-compatible** endpoint and **OpenAI**. Findings feed the real
`graphrag-plugin` and `ms_graphrag` retrieval phases.

- GraphRAG version pinned: **graphrag 3.1.0** (see `requirements.txt`).
- Isolated venv (`.venv`, Python 3.11) — intentionally NOT added to the pipeline image.

## Layout

```
fixture/input/*.txt     small SA/nuclear-domain corpus (3 docs)
cohere/settings.yaml    chat + embed via Cohere /compatibility/v1
openai/settings.yaml    chat + embed via OpenAI (reference; needs OPENAI key)
run_spike.py            load_config -> build_index -> global_search + local_search
```

## How to run

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
# Cohere (uses your Cohere key as GRAPHRAG_API_KEY):
GRAPHRAG_API_KEY=<cohere-key> .venv/bin/python run_spike.py cohere
# OpenAI:
GRAPHRAG_API_KEY=<openai-key> .venv/bin/python run_spike.py openai
```

## Findings (graphrag 3.1.0)

### Integration shape (confirmed)
- **Config**: `settings.yaml` with `completion_models:` + `embedding_models:` blocks
  (`model_provider: openai`, `model`, `api_base`, `auth_method: api_key`, `api_key`,
  `model_supports_json`, optional `call_args`, `retry`). Workflow sections reference
  models by id (`default_completion_model` / `default_embedding_model`). There is **no**
  `GraphRagConfig.from_file` in 3.1.0 — load via `graphrag.config.load_config.load_config(root_dir)`
  (it reads `<root>/settings.yaml` and **chdirs into the root**, so load one config per process).
- **API**: `graphrag.api.build_index(config, method=IndexingMethod.Standard|NLP, ..., input_documents=None, verbose)`;
  `global_search(config, entities, communities, community_reports, community_level, dynamic_community_selection, response_type, query, ...)`;
  `local_search(config, entities, communities, community_reports, text_units, relationships, covariates, community_level, response_type, query, ...)`.
- **Artifacts** (parquet under `output/`): `documents`, `text_units`, `entities`,
  `relationships`, `communities`, `community_reports` (+ `stats.json`, `context.json`,
  and a `lancedb/` vector store). These map cleanly to a future `graphrag_indexes` pointer row.
- **Custom OpenAI-compatible endpoints** work via `api_base` (Cohere compat = `https://api.cohere.com/compatibility/v1`).
- **Gotcha — `cache.type`** must be `json|memory|none` (the nested `cache.storage.type` is `file`). Setting `cache.type: file` fails with a misleading "CacheFactory: Registered types: ." error.
- No reranker stage (GraphRAG doesn't use one) — consistent with our provider abstraction marking optional providers `supports_rerank=false`.

### Cohere-compat results
- **Chat side works well.** `extract_graph` (entity/relationship extraction + gleanings),
  `summarize_descriptions`, `cluster_graph`, and `community_reports` all completed against
  `command-a-plus-05-2026` via the compat endpoint (~76s for the 3-doc fixture). Produced
  the full entity/relationship/community/report artifact set.
- **Embeddings via Cohere-compat work with one setting.** `generate_text_embeddings`
  initially failed with `pyarrow ArrowInvalid: length ... must be a multiple of the list_size`;
  the fix is `call_args.encoding_format: float` on the embedding model (graphrag issue #2194).
  A transient run then showed a lancedb dim mismatch (column 3072 vs query 1536), but a
  **direct probe of the compat `/embeddings` endpoint disproved a real incompatibility**:
  embed-v4.0 returns **1536 dims by default** and **honors `dimensions`** (1024→1024). The 3072
  came from a stale cache / vector-store dir, not the model. With caches cleared and
  `encoding_format: float`, index and query both embed at 1536 and agree.
- Do **not** set `call_args.dimensions` on this path — litellm rejects it for non
  `text-embedding-3` models on the openai provider, and it isn't needed (default 1536 is
  consistent).

### Recommendation for the real plugin (all-Cohere)
- Keep everything on **Cohere's OpenAI-compatibility endpoint**: chat = `command-a-plus`,
  embeddings = `embed-v4.0` with `encoding_format: float`. No OpenAI dependency, no mixed
  providers. The plugin resolves both models from the configured provider (`cohere_compat`),
  injecting `encoding_format: float` for the embedding model.

### Open item (run uninterrupted)
- A full `index → global_search → local_search` run takes ~2–3 min on the fixture. The
  chat-side index completed cleanly in-session; the end-to-end search run kept getting cut
  off by editor restarts, so it's worth one clean local run:
  `GRAPHRAG_API_KEY=<cohere-key> .venv/bin/python run_spike.py cohere`.
  Based on the probe + chat-side success, no further config changes are expected.

## Implications for the harness phases
- `graphrag-plugin`: a batch index job calling `build_index`, writing artifacts to per-(memory-space, configuration) storage, and recording a `graphrag_indexes` pointer row. Resolve chat + embed from the configured provider (all-Cohere via the compat endpoint by default), injecting `encoding_format: float` for the embedding model.
- `graphrag-retrieval`: an `ms_graphrag` strategy loading the parquet artifacts and calling `global_search`/`local_search`, registered in the stage registry (already stubbed) with a DB CHECK migration for the new `chat_messages.retrieval_mode`.
