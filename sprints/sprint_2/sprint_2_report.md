# Sprint 2 report

**Goal**: Cohere + Graphiti on FalkorDB, encrypted workspace API keys, settings/onboarding UI, internal Cohere test, docs and optional smoke test.

**Branch**: `sprints/sprint-2`  
**Status**: Complete — Graphiti synthetic smoke verified passing locally with Compose + host-published ports.

## Completed

- **Migrations**: `api_keys` table with partial unique index for one `llm_cohere` per workspace; merged default `pipeline_settings` (`0002_api_keys`). Follow-up **`0003_pipeline_models`** updates default Cohere model IDs workspace-wide (`command-r7b-12-2024`, `command-a-plus-05-2026`, `embed-v4.0`, `rerank-v4.0-fast`).
- **Pipeline**: `graphiti-core[falkordb]`, `graphiti_factory` (Falkor graph per workspace DB, `OpenAIGenericClient` + `CohereEmbedder` / `CohereCrossEncoder`), `POST /internal/v1/providers/cohere/test`, optional non-fatal `readyz` Cohere ping when `COHERE_API_KEY` is set, `/version` includes `graphiti-core` package version. **`EMBEDDING_DIM`** defaults to **1536** for embed v4 (Compose + Dockerfile).
- **Graphiti partitioning**: Explicit `group_id` on episode add + `group_ids` on search avoids Falkor driver default `\_`, which fails Graphiti’s `validate_group_id` (`^[a-zA-Z0-9_-]+$`).
- **Tests**: `tests/test_graphiti_smoke.py` runs when `ZKAST_GRAPHITI_SMOKE=1` and `COHERE_API_KEY` are set, with DB/Redis/Falkor reachable (see README host port map).
- **Web**: REST routes for api-keys and pipeline settings (Zod, no secrets in responses), AES-GCM aligned with pipeline, Settings UI + first-run modal (US-5.1 / US-5.2), proxy for **Test Cohere**.
- **Compose dev ergonomics**: Published **5432** (Postgres), **6379** (Redis), **6380→6379** (FalkorDB) for host-run pytest and local tools.
- **Docs**: Root README architecture, Cohere setup, `SEMAPHORE_LIMIT`, smoke env vars; pipeline README; `specs/apis.md` internal `cohere/test`; `specs/techstack.md` / `userstories.md` default model wording.

## Demo readiness

- Compose brings up migrations, web, pipeline; Settings saves encrypted `llm_cohere`, shows pipeline defaults, **Test Cohere** succeeds against stored key.
- Optional smoke: synthetic episode → hybrid search succeeds against live Cohere + FalkorDB (confirmed in QA).

## Gaps / follow-ups

- Ingestion, chat turns, and graph search HTTP routes remain **501** until later sprints.
- `readyz` does not probe Cohere when keys exist only in DB (`COHERE_API_KEY` env triggers the optional ping).
- Pytest smoke still requires **`COHERE_API_KEY`** even if only a DB key is configured (could be relaxed later).

## Next sprint prep

- Sprint 3 PDF ingestion should call `graphiti_for_workspace`, pass **`group_id`** = workspace UUID on `add_episode` / search-aligned APIs, and reuse encrypted keys + `pipeline_settings`.
