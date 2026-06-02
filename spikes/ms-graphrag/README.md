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
- **Embeddings (index) + global_search work on Cohere-compat.** A full uninterrupted run
  confirmed: all index workflows `ok` (incl. `generate_text_embeddings`) → 54 entities,
  61 relationships, 4 communities, 4 reports; **`global_search` returned a high-quality,
  citation-backed answer** (the headline GraphRAG capability). `generate_text_embeddings`
  requires `call_args.encoding_format: float` (graphrag issue #2194) — without it,
  `pyarrow ArrowInvalid: length ... must be a multiple of the list_size`.
- **`local_search` fails on an embedding-dim mismatch** (REAL, reproducible — not a cache
  artifact, correcting an earlier note): the entity vector store column is **3072-dim** while
  the query embeds at **1536** → `lance error: query dim(1536) doesn't match column vector
  dim(3072)`. A direct single-call probe of the compat endpoint returns **1536** (and honors
  `dimensions`), so the **index path produces 3072** — and `3072 = 2 × 1536` strongly suggests
  graphrag concatenates/doubles vectors when building the entity_description embeddings (e.g.
  name+description), or requests a different output size on that path. Global search is
  unaffected because it operates over community reports, not entity-vector similarity.

### Recommendation for the real plugin (all-Cohere)
- Keep everything on **Cohere's OpenAI-compatibility endpoint**: chat = `command-a-plus`,
  embeddings = `embed-v4.0` with `encoding_format: float`. No OpenAI dependency, no mixed
  providers. **Index + global_search are production-viable today.**
- **Open item (local_search):** reconcile the 3072 (stored) vs 1536 (query) entity-embedding
  dim. The compat endpoint honors `dimensions` directly (probe), so candidate fixes:
  (a) pin a fixed `dimensions` on both index + query — needs litellm to actually send it for
  embed-v4.0 (it blocks the param on the openai provider; investigate `litellm.drop_params` /
  `register_model` model_info); (b) inspect graphrag's `embed_text`/entity-embedding workflow
  to see where 3072 originates (likely a name+description concatenation) and align the query
  path. The first plugin can ship with **global search** working and gate local search on this.

## Runtime decision (DECIDED): dedicated `graphrag-worker` container
GraphRAG pulls **litellm → `openai>=2.20,<3`**, but the pipeline pins **`openai>=1.91,<2`**
(used by notes_llm, providers, ontology_autotune, raw-chunk embeddings). To avoid a risky
app-wide openai 2.x migration and keep heavy deps (spacy/onnxruntime/lancedb) out of the
main images, the GraphRAG plugin will run in a **dedicated `graphrag-worker` container** —
its own Dockerfile/requirements (py3.12 + graphrag 3.1.0 + openai 2.x), consuming a dedicated
arq queue, sharing the `apps/pipeline` codebase. Mirrors the existing `chat-worker` pattern.
The main pipeline/worker stay on openai 1.x and are untouched.

## Implications for the harness phases
- `graphrag-plugin`: a batch `build_index` job (on the dedicated graphrag-worker) writing
  artifacts to per-(memory-space, configuration) storage and recording a `graphrag_indexes`
  pointer row. Resolve chat + embed from the configured provider (all-Cohere via the compat
  endpoint by default), injecting `encoding_format: float` for the embedding model.
- `graphrag-retrieval`: an `ms_graphrag` strategy loading the parquet artifacts and calling `global_search`/`local_search`, registered in the stage registry (already stubbed) with a DB CHECK migration for the new `chat_messages.retrieval_mode`.
