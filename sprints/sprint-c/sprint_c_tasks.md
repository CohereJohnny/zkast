# Sprint C Tasks — Dreaming, Eval Modes, And Isolation

**Branch**: `sprints/sprint-c`
**Status**: Planning
**Primary spec**: [`specs/openspecs/north-agents-amem.md`](../../specs/openspecs/north-agents-amem.md)

## Goals

- Add agent-scoped dreaming jobs that evolve derived memory fields without mutating source text.
- Enforce strict agent isolation across links, retrieval, citations, and evals.
- Expand retrieval comparisons for North history across raw transcript, zettelkasten notes, A-MEM-lite, graph, and hybrid modes.
- Provide enough auditability to inspect every dreaming mutation.

## Tasks

### Phase 0 — Sprint Setup

- [ ] Branch `sprints/sprint-c` from updated `main` after Sprint B closes.
- [ ] Review Sprint B output and confirm North-derived notes have `agent_id` and embeddings.
- [ ] Review `specs/openspecs/north-agents-amem.md` for dreaming, retrieval, and eval acceptance criteria.
- [ ] Keep progress notes in this file as work proceeds.

### Phase 1 — Memory Links And Isolation

- [ ] Add link reason and link strength metadata for note links.
- [ ] Enforce that note links do not connect different non-null agent scopes.
- [ ] Add tests for same-agent links, legacy null-agent links, and cross-agent rejection.
- [ ] Ensure link reasons are inspectable in retrieval or review surfaces where useful.

### Phase 2 — Dreaming Jobs

- [ ] Add agent-scoped dreaming job records with status, timing, stats, and failure reason.
- [ ] For each dreaming job, retrieve nearest neighbor notes only within the selected agent.
- [ ] Apply allowed mutations only to derived fields and link metadata.
- [ ] Append evolution history for changed notes.
- [ ] Persist per-note mutation audit rows.
- [ ] Mark jobs complete or failed with inspectable stats.

### Phase 3 — Re-Embedding And Reindexing

- [ ] Re-embed notes when dreaming changes derived fields that affect retrieval.
- [ ] Keep immutable source text separate from derived retrieval text.
- [ ] Add job stats for notes considered, notes changed, links added, neighbors updated, and embeddings refreshed.
- [ ] Add tests for idempotent reindexing after dreaming.

### Phase 4 — Retrieval Mode Expansion

- [ ] Add or verify retrieval modes for `raw_transcript`, `zettelkasten_notes`, `amem_lite`, graph, and hybrid comparisons.
- [ ] Filter retrieval by selected agent when an agent scope is active.
- [ ] Prevent Naive-RAG, graph, and hybrid modes from mixing artifacts across agents.
- [ ] Add tests that retrieval records and citations respect agent scope.

### Phase 5 — North-History Eval Dataset

- [ ] Add a North-history eval dataset with single-hop, multi-hop, temporal, tool-provenance, and unanswerable categories.
- [ ] Let the eval runner accept an optional agent scope.
- [ ] Persist mode, category, score, answer, citation, and refusal results for review.
- [ ] Include refusal expectations for questions outside the selected agent's memory.

### Phase 6 — Tests And Closeout

- [ ] Add focused tests for dreaming audit records and mutation constraints.
- [ ] Add focused tests for cross-agent retrieval and link isolation.
- [ ] Run pipeline tests covering retrieval, eval scoring, and dreaming.
- [ ] Document accepted limitations or follow-ups in `sprints/tech_debt.md`.

## Definition Of Done

- [ ] Dreaming can run for one agent without mutating source text.
- [ ] Dreaming mutations are auditable at job and per-note levels.
- [ ] Retrieval and citations respect active agent scope across all supported modes.
- [ ] Cross-agent note links are rejected unless explicitly allowed by a future spec.
- [ ] North-history eval dataset exists and can compare planned retrieval modes.
- [ ] Sprint C tests pass.

## Notes

- Sprint C depends on Sprint B's enriched, embedded, agent-scoped notes. Product-facing polish belongs in Sprint D unless needed to validate isolation or dreaming behavior.
