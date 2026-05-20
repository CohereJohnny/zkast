# Sprint D report

**Status**: Complete — merged to `main`.
**Branch**: `sprints/sprint-d`
**Spec anchors**: [`north-agents-amem.md`](../../specs/openspecs/north-agents-amem.md) (UI requirements, AC-5..AC-8); [`dreaming.md`](../../specs/dreaming.md); canonical [`datamodel.md`](../../specs/datamodel.md), [`apis.md`](../../specs/apis.md), [`uiux.md`](../../specs/uiux.md), [`userstories.md`](../../specs/userstories.md)

## Shipped

| Area | Summary |
| ---- | ------- |
| **Chat agent scope (TD-016)** | Replaced manual UUID input in `chat-scope-picker.tsx` with the existing `AgentPicker`; `ChatPanel` accepts an `initialAgentId`; chat page reads `?agent_id=`; header shows an active memory-boundary chip resolved by display name with a one-click "Clear agent scope" |
| **Deep links** | `Open in chat` link on Agent detail; `Chat` action on each row of the Agents list |
| **Dream status polish** | Status card now shows `notes`, `pairs`, `links`, `neighbors`, `embeddings` on terminal jobs and surfaces recovery guidance on failure |
| **Spec sync** | Added North/A-MEM/Dreaming sections to `datamodel.md`; added dream-job endpoints + `sync_status` note to `apis.md`; added Agents surface, agent-scoped Notes/Graph/Chat/Eval, and Dream UX to `uiux.md`; added Epic 10 (US-10.1..US-10.6) to `userstories.md`; added AC-5..AC-8 to `north-agents-amem.md` for shipped UI behavior |

## Definition of done

- [x] North A-MEM demo path runs end to end without manual UUID entry or SQL
- [x] Chat agent scope uses `AgentPicker`; selected agent is preserved across navigation
- [x] Agent scope is visible and reversible across Notes, Graph, Chat, and Eval
- [x] Canonical specs match shipped behavior; OpenSpec stays implementation-agnostic
- [x] Sprint D tests + `tsc --noEmit` green

## Gaps / deferred

- A fuller eval results UI (per-mode, per-category drilldown) remains a backlog candidate — current CLI/internal API surface is enough for the demo flow.
- No new platform capabilities were added; new ideas should go to `backlog.md`.

## Next

North + A-MEM track is closed for now. Future polish (richer eval inspection, multi-agent visualizations) can be planned from `backlog.md` when prioritized.
