# Sprint B report

**Status**: Implementation complete on branch `sprints/sprint-b`.
**Build**: web `tsc --noEmit` green; pipeline Sprint B tests pass (unit + skipped DB tests without `DATABASE_URL`).
**Spec**: [north-agents-amem.md](../../specs/openspecs/north-agents-amem.md) — FR-7, FR-9 (agent-scoped retrieval inputs).

## Shipped

| Area | Summary |
| ---- | ------- |
| **A-MEM enrichment** | North-only (`agent_scope`); tag merge; job log + metrics; `mark_dreaming_touch` split from enrichment; batch resilience |
| **Note embeddings** | `backfill_note_embeddings`; extended `retrieval-index/status` + `backfill` with `kinds` + optional `agent_id` |
| **Agent UI** | `AgentPicker`; agent detail stats + links; graph `agent_id` filter; agents list Notes/Graph links |
| **Diagnostics** | Retrieval index counts + backfill buttons for raw chunks and note indexes |
| **Tests** | `test_amem_enrich`, `test_note_embedding_index`, `test_notes_agent_filter`, `test_graph_agent_filter` |

## Definition of done

- [x] North-derived notes receive A-MEM enrichment with immutable bodies and pipeline log lines.
- [x] `note_zettel` / `note_amem` backfill path with `agent_id` on index rows.
- [x] Agent detail, notes, and graph use agent pickers (not raw UUIDs).
- [x] Mixed workspace: unscoped notes list includes PDF + North; scoped list filters by agent.
- [x] Sprint B tests + web typecheck green.
- [x] Sprint C scope unchanged (dream button only; no dreaming audit UI).

## Next

Sprint C — dreaming jobs, link isolation, re-embed after dreaming ([sprint_c_tasks.md](../sprint-c/sprint_c_tasks.md)).
