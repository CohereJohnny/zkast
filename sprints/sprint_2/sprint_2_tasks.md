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

- [ ] Settings → API Keys UI: add **Cohere** key form (`kind` = `llm_cohere` per [datamodel.md](../../specs/datamodel.md)).
- [ ] Mask secret after save; show label + last_used_at only (**FR-30**).
- [ ] Pipeline settings read-only display: default models (`command-r`, `command-r-plus`, embed, rerank) per [techstack.md](../../specs/techstack.md); provider selector disabled with copy (**US-5.2**).
- [ ] First-run modal / onboarding route: prompt for `COHERE_API_KEY` ([uiux.md](../../specs/uiux.md) single-user flow).

## Pipeline service

- [ ] Install `graphiti-core` + FalkorDB extra per [techstack.md](../../specs/techstack.md).
- [ ] Implement **Graphiti** construction: `OpenAIGenericClient` pointed at `https://api.cohere.com/compatibility/v1` with workspace API key.
- [ ] Custom **Embedder** wrapping Cohere Embed API v3.
- [ ] Custom **Cross-encoder / reranker** wrapping Cohere Rerank v3 (Graphiti rerank slot).
- [ ] Initialize indices/constraints on FalkorDB (follow Graphiti quickstart).
- [ ] `POST /internal/v1/providers/cohere/test` — ping chat + embed + rerank with minimal payloads.
- [ ] Force `GRAPHITI_TELEMETRY_ENABLED=false` in compose (**NFR-2**).

## Data + migrations

- [ ] `api_keys` table: `kind` enum includes `llm_cohere`; encrypt `encrypted_secret` with master key (**NFR-3**).
- [ ] `workspace.pipeline_settings` JSON: defaults for chat small/large, embed, rerank models.

## Infra + Docker

- [ ] Pass-through env for dev; production pattern: secrets only in DB after first-run.
- [ ] Document rate-limit tuning (`SEMAPHORE_LIMIT` from Graphiti README) in README.

## Design + UX

- [ ] First-run screen matches tokens; clear copy that only Cohere is contacted (**US-5.1** AC-3).

## Docs

- [ ] Document obtaining Cohere production key and required models.
- [ ] Architecture diagram update in README (web ↔ pipeline ↔ FalkorDB ↔ Cohere).

---

## Definition of Done

- [ ] Smoke script: insert synthetic episode → Graphiti extracts / retrieves without unhandled schema errors.
- [ ] API returns no secret fields on any response.
- [ ] FalkorDB data persists across container restart (named volume).

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

### Gaps / issues

### Next sprint prep
