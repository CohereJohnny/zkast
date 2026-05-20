# Sprint C Tasks — Dreaming, Eval Modes, And Isolation

**Branch**: `sprints/sprint-c`
**Status**: Implementation complete
**Primary spec**: [`specs/openspecs/north-agents-amem.md`](../../specs/openspecs/north-agents-amem.md) — **FR-6**, **FR-8**, **FR-9**, **FR-10**
**Depends on**: Sprint B ([`sprint_b_report.md`](../archive/sprint-b/sprint_b_report.md))

## Goals

- Run **agent-scoped dreaming** jobs that evolve derived memory fields without mutating immutable source text.
- Enforce **strict agent isolation** across note links, retrieval hits, citations, and eval runs.
- Verify and harden **retrieval mode** comparisons under optional `agent_id` scope.
- Provide **auditable** dreaming mutations at job and per-note levels.

---

## Tasks

### Phase 0 — Sprint setup

- [x] Branch `sprints/sprint-c` from updated `main` after Sprint B merge.
- [x] Sprint B dependencies documented (A-MEM fields, indexes, AgentPicker).
- [x] FR-6, FR-8, FR-9, FR-10 reviewed against implementation.

**Progress:** Branch + plan on `68bbfe2`; implementation commit follows.

---

### Phase 1 — Memory links and isolation

- [x] Schema confirmed (`link_reason`, `link_strength` on `note_links`; `fetch_note_detail` returns both).
- [x] `add_note_link` documented: cross-agent forbidden only when both `agent_id` non-null and differ; PDF↔North allowed.
- [x] Regression tests: `test_note_link_isolation.py`.

**Progress:** One-sided null `agent_id` links allowed (not stricter rejection).

---

### Phase 2 — Dreaming jobs (productionize)

- [x] `GET .../north/agents/{agent_id}/dream-jobs` and `GET .../dream-jobs/{job_id}` (+ web proxies).
- [x] `POST .../dream` creates `dream_jobs` row first, returns `job_id`, passes to worker.
- [x] Pipeline caps: `dreaming_max_notes`, `dreaming_neighbors_per_note`, `dreaming_pairs_per_run`.
- [x] Immutability guard after `patch_note_derivations`.
- [x] Status vocabulary: `running` / `succeeded` / `failed`.
- [x] Minimal UI: `DreamJobStatus` on Agents list + agent detail Dream button.

**Progress:** Stats in `dream_jobs.stats`; arq `_job_id` prefix `dream:{agent_id}:{job_id}`.

---

### Phase 3 — Re-embedding and reindexing

- [x] Post-dream `upsert_amem_embeddings_for_notes` with `embeddings_refreshed` stat.
- [x] Idempotent upsert test in `test_note_embedding_index.py`.
- [x] Zettel unchanged by design (dreaming never mutates `title`/`body`).

---

### Phase 4 — Retrieval mode expansion and agent scope

- [x] Agent filter verified for `raw_transcript`, `zettelkasten_notes`, `amem_lite` (`test_retrieval_agent_scope.py`).
- [x] Graph/hybrid already pass `scope.agent_id` (Sprint B).
- [x] `retrieval_records` prefix `scope_snapshot` item when scope has `agent_id`.
- [x] Chat scope picker agent UX deferred → TD-016 (Sprint D).

---

### Phase 5 — North-history eval dataset

- [x] Expanded `north_history_v1.yaml` (8 questions, all categories).
- [x] `NORTH_HISTORY_MODES` + `default_modes_for_dataset()`; internal eval + CLI use north modes for that dataset.
- [x] `README_north_history.md` seed/run instructions.
- [x] `StartEvalBody.agent_id` already wired.

---

### Phase 6 — Tests and closeout

- [x] `test_dreaming_job.py`, `test_note_link_isolation.py`, `test_retrieval_agent_scope.py`, `test_eval_north_modes.py`.
- [x] Web `tsc --noEmit` green.
- [x] TD-016 logged for chat scope picker polish.

---

## Definition of done

- [x] Dreaming runs for one agent without mutating note `body`.
- [x] Dreaming mutations auditable (`dream_jobs`, `dream_job_mutations`, `evolution_history`).
- [x] Retrieval/eval respect `agent_id` across supported modes.
- [x] Cross-agent note links rejected (two non-null different agents).
- [x] North-history eval dataset + modes defined; CLI/API support `agent_id`.
- [x] Sprint C unit tests pass; web typecheck green.

---

## Sprint review

**Demo readiness:** Dream from Agents or agent detail → poll job status (links/neighbors/embeddings counts). Note detail shows link reasons. Scoped Notes/Graph via AgentPicker (Sprint B). Eval: `north_history_v1` + `--agent-id` with five retrieval modes.

**Gaps / issues:** Chat scope still uses manual agent UUID (TD-016). No dedicated eval UI panel (CLI/internal API only). Graph/hybrid agent isolation depends on Graphiti document `agent_id` at ingest time.

**Closeout (final commit):** North import sync status + ingest hash dedup; A-MEM count fix; chat `amem_lite` migration; dreaming pipeline telemetry; pipeline log docked on agent detail; `specs/dreaming.md`.

**Next steps:** Sprint D — product polish, chat AgentPicker, spec sync.
