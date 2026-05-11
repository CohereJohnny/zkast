# Sprint 2 — Cohere and Graphiti Integration

**Duration**: 2 weeks  
**Goal**: Wire **Cohere** (Command via OpenAI-compat, Embed v3, Rerank v3) into **graphiti-core** with **FalkorDB** driver; persist encrypted **`ApiKey`** (`llm_cohere`); first-run UI to save key; test-connection flows. Unlocks all LLM-backed pipeline work. **FR-29**, **FR-30**, **NFR-3**, foundations for **FR-12–FR-15**.

## Inputs

- Sprint 1 scaffold + Postgres + FalkorDB container.
- [techstack.md](../../specs/techstack.md) Cohere + Graphiti section.
- [datamodel.md](../../specs/datamodel.md) `ApiKey`, `Workspace.pipeline_settings`.

## Outputs

- Pipeline can initialize Graphiti against FalkorDB and run a minimal scripted episode ingest smoke test (fixtures).
- Workspace settings API + UI: store Cohere key encrypted; never return secret ([apis.md](../../specs/apis.md) Settings & API Keys pattern).
- "Test Cohere" returns structured OK/provider error.

## Dependencies

- **Sprint 1** complete.

---

## Web tier

- [x] Settings → API Keys UI: add **Cohere** key form (`kind` = `llm_cohere` per [datamodel.md](../../specs/datamodel.md)).
- [x] Mask secret after save; show label + last_used_at only (**FR-30**).
- [x] Pipeline settings read-only display: default models (`command-r7b-12-2024`, `command-a-plus-05-2026`, `embed-v4.0`, `rerank-v4.0-fast`) per [techstack.md](../../specs/techstack.md); provider selector disabled with copy (**US-5.2**).
- [x] First-run modal / onboarding route: prompt for `COHERE_API_KEY` ([uiux.md](../../specs/uiux.md) single-user flow).

## Pipeline service

- [x] Install `graphiti-core` + FalkorDB extra per [techstack.md](../../specs/techstack.md).
- [x] Implement **Graphiti** construction: `OpenAIGenericClient` pointed at `https://api.cohere.com/compatibility/v1` with workspace API key.
- [x] Custom **Embedder** wrapping Cohere Embed API v3.
- [x] Custom **Cross-encoder / reranker** wrapping Cohere Rerank v3 (Graphiti rerank slot).
- [x] Initialize indices/constraints on FalkorDB (follow Graphiti quickstart).
- [x] `POST /internal/v1/providers/cohere/test` — ping chat + embed + rerank with minimal payloads.
- [x] Force `GRAPHITI_TELEMETRY_ENABLED=false` in compose (**NFR-2**).

## Data + migrations

- [x] `api_keys` table: `kind` enum includes `llm_cohere`; encrypt `encrypted_secret` with master key (**NFR-3**).
- [x] `workspace.pipeline_settings` JSON: defaults for chat small/large, embed, rerank models.

## Infra + Docker

- [x] Pass-through env for dev; production pattern: secrets only in DB after first-run.
- [x] Document rate-limit tuning (`SEMAPHORE_LIMIT` from Graphiti README) in README.

## Design + UX

- [x] First-run screen matches tokens; clear copy that only Cohere is contacted (**US-5.1** AC-3).

## Docs

- [x] Document obtaining Cohere production key and required models.
- [x] Architecture diagram update in README (web ↔ pipeline ↔ FalkorDB ↔ Cohere).

---

## Definition of Done

- [x] Smoke script: insert synthetic episode → Graphiti extracts / retrieves without unhandled schema errors (optional `ZKAST_GRAPHITI_SMOKE=1`).
- [x] API returns no secret fields on any response.
- [x] FalkorDB data persists across container restart (named volume).

## Risks and mitigations

| Risk | Mitigation |
| ---- | ---------- |
| Structured-output failures on small models | Document minimum model tier; integration test on `command-r` |
| Cohere compat endpoint drift | Pin SDK versions; contract test against mock |

## Out of scope

- Full PDF pipeline (**Sprint 3**).
- Atomic-note Zettel prompts (**Sprint 4**).

---

## Sprint review (fill at end)

### Demo readiness

- Docker Compose applies migration `0002_api_keys`; Settings stores encrypted `llm_cohere`; **Test Cohere** proxies to `POST /internal/v1/providers/cohere/test` using the **stored** key.
- Pipeline builds Graphiti with FalkorDB (`zkast_ws_<workspace>` graph) and Cohere adapters; `/version` exposes `graphiti-core` wheel version.
- Optional pytest smoke adds a synthetic episode and searches when `ZKAST_GRAPHITI_SMOKE=1` and infrastructure + `COHERE_API_KEY` are available.

### Gaps / issues

- Core ingestion/chat/graph HTTP routes remain stubbed (later sprints).
- Readiness `cohere` check runs only when `COHERE_API_KEY` env is set (DB-only installs skip automatic LLM ping on `/readyz`).

### Next sprint prep

- Wire PDF ingestion to `graphiti_for_workspace` + episode APIs; reuse pipeline settings and encrypted keys.
