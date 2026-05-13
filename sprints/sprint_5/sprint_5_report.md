# Sprint 5 report

**Status**: Complete (implementation + docs + tests).  
**Build**: `pnpm run build` — green.  
**Tests**: `apps/pipeline/tests/test_sprint5_graph.py` — requires `DATABASE_URL` and Alembic through **`0006_graph_snapshots`** (otherwise skipped).

## Shipped

| Area | Summary |
| ---- | ------- |
| **DB** | `0006_graph_snapshots` — immutable snapshot tables with frozen JSON payloads. |
| **Pipeline** | `graph_repo` (overview/subgraph, filters, truncation), `get_entity_detail` + **`incident_relationships`**, `graph_edit_repo`, `snapshots_repo`, `internal_graph` router. |
| **Web** | API route proxies; `graph-canvas` (Sigma + FA2 **worker**); filter bar; workspace graph panel with error boundary + accessible list; selection panel + `entity-merge-dialog` + `graph-edge-popover`; snapshots UI. |
| **Notes** | Merge dialog: pre-merge survivor snapshot + optional **revert survivor fields** after merge. |
| **QA** | Integration-style pytest coverage for graph list, subgraph, merge, manual relationship + end, empty snapshot rejection, snapshot lifecycle. |

## Definition of Done

- Graph canvas and list fallback functional; URL-synced filters documented.
- Entity merge and relationship end persist correctly in Postgres; UI exposes edit/end/create.
- Snapshot create rejects empty graph; list/delete exercised in tests when data present.

## Follow-ups (not blocking)

- Full transactional undo for merge (restore deleted row) would need new internal endpoints.
- Graph search (`GET /graph/search`) for a later sprint.

*Note: Workspace was not a git repository in the dev environment used for this sprint — no `sprints/sprint-5` branch or PR was created here.*
