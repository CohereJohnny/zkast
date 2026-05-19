# Sprint B Tasks — A-MEM Embeddings And Agent UI

**Branch**: `sprints/sprint-b`
**Status**: Planning
**Primary spec**: [`specs/openspecs/north-agents-amem.md`](../../specs/openspecs/north-agents-amem.md)

## Goals

- Enrich North-derived atomic notes with A-MEM-style memory metadata.
- Add agent-scoped note embeddings for North-derived memories.
- Make agent-scoped notes and conversations visible in the workspace UI.
- Prepare retrieval inputs for Sprint C's dreaming, eval, and isolation hardening.

## Tasks

### Phase 0 — Sprint Setup

- [ ] Branch `sprints/sprint-b` from updated `main` after Sprint A closes.
- [ ] Review Sprint A output and confirm North-derived notes carry `agent_id`.
- [ ] Review `specs/openspecs/north-agents-amem.md` for Sprint B acceptance criteria.
- [ ] Keep progress notes in this file as work proceeds.

### Phase 1 — A-MEM Note Enrichment

- [ ] Add derived memory fields for context, keywords, tags, and evolution history.
- [ ] Run enrichment after note generation for eligible North-derived notes.
- [ ] Preserve immutable transcript, episode, and note body source text.
- [ ] Record enrichment failures in job logs without silently skipping affected notes.

### Phase 2 — Note Embeddings

- [ ] Add or extend note embedding indexes for North-derived atomic memories.
- [ ] Store `agent_id` on relevant retrieval index rows.
- [ ] Backfill embeddings for existing North-derived notes.
- [ ] Report embedding status per agent or workspace.

### Phase 3 — Agent UI

- [ ] Show agent detail with imported conversations and derived note counts.
- [ ] Add note list filters for selected agent scope.
- [ ] Add graph view filters for selected agent scope.
- [ ] Add loading, empty, and error states for agent-scoped views.

### Phase 4 — Mixed-Agent Boundaries

- [ ] Confirm workspace-wide PDF notes remain visible when no agent scope is selected.
- [ ] Confirm selecting an agent limits North-derived notes to that agent.
- [ ] Confirm agent filters do not hide unrelated workspace navigation.
- [ ] Add regression tests for mixed PDF and North workspace views.

### Phase 5 — Tests

- [ ] Add tests for enrichment output shape and source-text immutability.
- [ ] Add tests for agent-scoped embedding persistence.
- [ ] Add tests for agent filters in notes and graph views.
- [ ] Run focused pipeline and web checks for enrichment, embeddings, and UI flows.

## Definition Of Done

- [ ] North-derived notes can be enriched with A-MEM-style context, keywords, and tags.
- [ ] North-derived notes have agent-scoped embeddings ready for retrieval.
- [ ] Agent detail, notes, and graph views expose useful agent-scoped state.
- [ ] Mixed PDF and North workspaces remain understandable and navigable.
- [ ] Sprint B tests pass.

## Notes

- Sprint B depends on Sprint A's North import and provenance foundation. Dreaming, retrieval-mode evals, and strict isolation hardening are tracked in Sprint C.
