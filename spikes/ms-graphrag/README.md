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
- **Embeddings via Cohere-compat are problematic** (chain of issues):
  1. `generate_text_embeddings` failed with `pyarrow ArrowInvalid: length ... must be a multiple of the list_size`. Fix: set `call_args.encoding_format: float` on the embedding model (graphrag issue #2194).
  2. After that, search failed with a lancedb **dim mismatch**: indexed vectors were **3072-dim** (embed-v4.0) but the query embedded at **1536**.
  3. Pinning `call_args.dimensions: 1536` is rejected by litellm (`UnsupportedParamsError: Setting dimensions is not supported for ... text-embedding-3 and later`) on the openai provider path.

### Recommendation for the real plugin
- **Mixed providers**: run the GraphRAG **chat** model on the configured provider
  (Cohere-compat or OpenAI) and the **embedding** model on **OpenAI** (`text-embedding-3-small`,
  well-supported by litellm) — GraphRAG supports per-model config. This sidesteps the
  Cohere-compat embedding quirks and is exactly why the harness has a configurable-provider
  abstraction. Example:

  ```yaml
  completion_models:
    default_completion_model:
      model_provider: openai
      model: command-a-plus-05-2026
      api_base: https://api.cohere.com/compatibility/v1
      api_key: ${COHERE_API_KEY}
      model_supports_json: true
  embedding_models:
    default_embedding_model:
      model_provider: openai
      model: text-embedding-3-small
      api_key: ${OPENAI_API_KEY}
  ```

- If an all-Cohere embedding path is required, follow up on: aligning the lancedb vector
  size to embed-v4.0's native dim (3072) so index and query agree, and/or litellm
  `drop_params`. Tracked as an open item — not required for the first plugin.

### Open items (need an OpenAI key / live run)
- Run `run_spike.py openai` end-to-end (no key was available in this environment) and the
  mixed chat=Cohere/embed=OpenAI config, then capture global vs local answer quality and
  cost/latency vs the Graphiti backend.

## Implications for the harness phases
- `graphrag-plugin`: a batch index job calling `build_index`, writing artifacts to per-(memory-space, configuration) storage, and recording a `graphrag_indexes` pointer row. Resolve chat+embed providers via our provider abstraction (embed defaulting to OpenAI).
- `graphrag-retrieval`: an `ms_graphrag` strategy loading the parquet artifacts and calling `global_search`/`local_search`, registered in the stage registry (already stubbed) with a DB CHECK migration for the new `chat_messages.retrieval_mode`.
