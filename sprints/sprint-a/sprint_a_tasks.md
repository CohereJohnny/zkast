# Sprint A Tasks — North Source Foundation

**Branch**: `sprints/sprint-a`
**Status**: Complete (implementation verified + Sprint A rework)
**Primary spec**: [`specs/openspecs/north-agents-amem.md`](../../specs/openspecs/north-agents-amem.md)

## Goals

- Add North as a first-class ingestion source alongside PDFs.
- Let an operator configure North connectivity and register/sync North agents.
- Import North conversations into the existing document, episode, notes, graph, and job pipeline while preserving agent provenance.
- Establish strict agent-scoped data boundaries for all North-derived artifacts.

## Tasks

### Phase 0 — Sprint Setup

- [x] Confirm branch `sprints/sprint-a` is based on updated `main`.
- [x] Confirm Sprint 6c is merged and pushed to `main`.
- [x] Review `specs/openspecs/north-agents-amem.md` for Sprint A acceptance criteria.
- [x] Keep progress notes in this file as work proceeds.

**Progress:** `HEAD` matches `main` at merge commit including Sprint 6c North foundation; Sprint A work layers validation, fail-fast import, cursor persistence, UI job wiring, and tests.

### Phase 1 — North Connectivity

- [x] Add per-workspace North connection settings for base URL and bearer token.
- [x] Store North bearer token using the existing encrypted credential mechanism.
- [x] Add a North connection test flow with clear success and failure states.
- [x] Ensure North credentials are only used server-side.

**Progress:** Settings UI + `north_bearer` `api_keys` row + `pipeline_settings.north_base_url`; pipeline `POST /internal/.../north/test-connection` proxied as `/providers/north/test`. Added initial settings load indicator and isolated **Test North** busy state so connectivity checks do not block the rest of the form.

### Phase 2 — Agent Registration

- [x] Add local North agent records with provider, external agent id, display metadata, import defaults, and sync cursor fields.
- [x] Enforce uniqueness for agent registration within a workspace and provider.
- [x] Add a sync flow that lists remote North agents and upserts local agent records.
- [x] Surface agent sync errors without creating partial or ambiguous agent state.

**Progress:** `north_agents` + `POST .../north/agents/sync`; remote list failures return 502 with `north_upstream_error`. Conversation list refresh now persists `sync_cursor` via `update_agent_sync_cursor` after each North list page.

### Phase 3 — Conversation Cache

- [x] Add a North conversation cache for raw or normalized conversation payloads.
- [x] Enforce uniqueness for cached conversations per agent.
- [x] Support listing and fetching conversations for a selected registered agent.
- [x] Preserve fetched payloads for replay, debugging, and re-import.

**Progress:** `north_conversation_cache` + list from cache or refresh-from-North; import and refresh upsert full payloads. Conversation payloads normalized to a dict root (`messages` wrapper for list bodies) before cache/write.

### Phase 4 — Import Into Ingestion Spine

- [x] Extend document provenance for `north_conversation` sources.
- [x] Require `agent_id` for North-derived documents.
- [x] Segment conversation transcripts into content-bearing episodes.
- [x] Carry `agent_id` from agent to document to episode.
- [x] Enqueue the existing parse, notes, graph, and indexing stages for imported conversations.
- [x] Fail fast with a clear validation message when filters produce an empty transcript.

**Progress:** Import reuses `insert_document` + `parse_document` → `_parse_north_transcript`. **New:** `count_north_episode_rows_from_conversation` dry-run before inserting a document; empty after filters returns **422** `north_empty_transcript` (no orphan `documents` / `ingestion_runs`). Worker still raises if zero episodes slip through.

### Phase 5 — User Surface

- [x] Add an Agents navigation entry or equivalent workspace entry point.
- [x] Show registered North agents with provider, name, sync state, and last sync metadata.
- [x] Let an operator open agent details and browse available conversations.
- [x] Let an operator import a selected conversation and monitor the resulting job.

**Progress:** Left rail `/agents`; list + detail panels. **New:** import registers `job_id` with `JobEventsProvider` (`document_parse`) and shows dedupe / started notices; conversation list shows loading state; refresh button uses explicit busy state.

### Phase 6 — Isolation and Regression Tests

- [x] Add tests that North imports cannot create documents without a valid agent.
- [x] Add tests that North-derived episodes and notes carry matching `agent_id`.
- [x] Add tests that duplicate conversation imports follow the documented idempotency policy.
- [x] Confirm existing PDF ingestion still works after North source additions.

**Progress:** Import handler returns **404** if `fetch_north_agent` misses (no document created). **New tests:** `apps/pipeline/tests/test_north_transcript_episodes.py` — zero episodes after filters, positive count, `agent_id` on every built episode row. **Dedup:** same transcript checksum returns **200** `{ deduped: true, job_id: null }` (documented in UI copy). PDF path unchanged; `tsc --noEmit` clean.

## Definition Of Done

- [x] Operator can configure North credentials and verify connectivity.
- [x] Operator can sync/register North agents into a workspace.
- [x] Operator can import a North conversation and see agent-scoped documents and episodes.
- [x] Imported conversations enter the existing notes/graph pipeline without breaking PDF ingestion.
- [x] Agent provenance is present on all North-derived source artifacts.
- [x] Sprint A tests pass.

## Notes

- Sprint A should establish the source and provenance foundation only. A-MEM enrichment, dreaming, note embedding expansion, and eval comparisons are tracked in Sprint B unless needed to unblock Sprint A validation.

## Sprint Review

**Demo readiness:** Operators can configure North in Settings, sync agents, browse conversations on `/agents` and `/conversations`, import transcripts into the existing ingestion spine, and tail pipeline jobs from the docked log on Documents and Conversations. PDF upload and ingestion are unchanged.

**Gaps / issues:** Chat turns still use `useChatStream` only (not `JobLogConsole`). Manual smoke on a live North tenant is still recommended before production use.

**Next steps:** Sprint B — A-MEM note enrichment, agent-scoped embeddings, and mixed source views per [sprint_b_tasks.md](../sprint-b/sprint_b_tasks.md).
