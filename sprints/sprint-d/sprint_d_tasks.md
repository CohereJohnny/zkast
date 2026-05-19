# Sprint D Tasks — Product Polish And Spec Closeout

**Branch**: `sprints/sprint-d`
**Status**: Planning
**Primary spec**: [`specs/openspecs/north-agents-amem.md`](../../specs/openspecs/north-agents-amem.md)

## Goals

- Productize the North agent memory experience across Settings, Agents, Notes, Graph, Chat, and Eval surfaces.
- Tighten loading, empty, error, and success states for agent-scoped workflows.
- Bring specs and sprint documentation back into alignment with shipped behavior.
- Prepare the North A-MEM track for handoff, demo, or release review.

## Tasks

### Phase 0 — Sprint Setup

- [ ] Branch `sprints/sprint-d` from updated `main` after Sprint C closes.
- [ ] Review Sprint A-C task files and reports for gaps.
- [ ] Review `specs/openspecs/north-agents-amem.md` against shipped behavior.
- [ ] Keep progress notes in this file as work proceeds.

### Phase 1 — Settings And Agents Polish

- [ ] Confirm North connectivity settings have clear validation, loading, success, and failure states.
- [ ] Confirm synced agents show provider, display name, sync state, and useful timestamps.
- [ ] Add or refine empty states for no credentials, no agents, no conversations, and no imports.
- [ ] Ensure destructive or expensive actions require clear confirmation.

### Phase 2 — Agent-Scoped Workspace Filters

- [ ] Make selected agent scope clear across Notes, Graph, Chat, and Eval views.
- [ ] Provide an obvious way to return from agent-scoped view to workspace-wide view.
- [ ] Confirm filters do not imply cross-agent blending when isolation is active.
- [ ] Validate keyboard and screen-reader behavior for new controls.

### Phase 3 — Chat And Citation Review

- [ ] Confirm agent-scoped chat labels the active memory boundary.
- [ ] Confirm citations distinguish raw transcript, notes, graph artifacts, and A-MEM-derived context where available.
- [ ] Confirm refusal behavior is understandable when a question falls outside selected agent scope.
- [ ] Add lightweight copy for retrieval-mode differences if comparison UI is present.

### Phase 4 — Dreaming And Eval Review Surfaces

- [ ] Show dreaming job status, stats, failures, and recent mutation history.
- [ ] Make eval-run results inspectable by mode and category.
- [ ] Surface agent scope in eval-run details and result summaries.
- [ ] Add recovery guidance for failed dreaming or eval runs.

### Phase 5 — Spec Sync

- [ ] Update `specs/datamodel.md` to reflect shipped North, A-MEM, dreaming, and retrieval fields.
- [ ] Update `specs/apis.md` to reflect shipped North, dreaming, eval, and retrieval endpoints.
- [ ] Update `specs/uiux.md` for shipped Agents and agent-scoped workspace flows.
- [ ] Update `specs/userstories.md` with any new accepted user-facing behavior.
- [ ] Keep `specs/openspecs/north-agents-amem.md` focused on WHAT was required, not implementation details.

### Phase 6 — Final Validation

- [ ] Run focused pipeline tests for North import, enrichment, retrieval, dreaming, and eval.
- [ ] Run focused web checks for Settings, Agents, Notes, Graph, Chat, and Eval surfaces.
- [ ] Run build or typecheck commands required by the project before closeout.
- [ ] Log non-critical follow-ups in `sprints/tech_debt.md` or `sprints/backlog.md`.

## Definition Of Done

- [ ] North A-MEM flows are demo-ready from settings through import, memory review, dreaming, and scoped chat/eval.
- [ ] UI states are clear for loading, empty, error, and success conditions.
- [ ] Specs match shipped behavior without embedding implementation details.
- [ ] Known gaps are captured in central logs.
- [ ] Sprint D tests and build checks pass.

## Notes

- Sprint D should avoid introducing new platform capabilities unless they are required to close acceptance gaps from the North A-MEM spec. New ideas should go to `sprints/backlog.md`.
