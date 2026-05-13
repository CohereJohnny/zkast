# Sprint 5 — Graph Visualization, Editing, and Snapshots

**Goal**: Working knowledge graph (Sigma + graphology + FA2 worker), URL-synced filters, provenance panel, entity merge with survivor-field undo, relationship CRUD, named GraphSnapshots, Notes merge/split polish.

**Inputs**: Sprint 5 plan (attached in repo context), `specs/apis.md`, `specs/datamodel.md`.

---

## Tasks (all complete)

- [x] Alembic `0006_graph_snapshots`: `graph_snapshots`, `snapshot_entities`, `snapshot_relationships`, `snapshot_notes` + indexes
- [x] Pipeline `graph_repo` + `internal_graph`: `GET /graph`, `GET/PATCH/DELETE …/graph/entities/{id}`, `POST …/merge`, relationship routes, snapshots routes
- [x] `graph_edit_repo`: entity patch/merge/delete, manual relationship insert, patch, end (`valid_to`)
- [x] `snapshots_repo`: `REPEATABLE READ` freeze transaction, list/get/delete, empty-graph `SnapshotError`
- [x] Next.js API proxies under `apps/web/src/app/api/v1/workspaces/[workspaceId]/graph*` and `snapshots*`
- [x] `graph-canvas.tsx`: Sigma + graphology + **ForceAtlas2 Web Worker**; type-based size/border; static layout when `prefers-reduced-motion`
- [x] `graph-filter-bar.tsx` + URL state (`useSearchParams`)
- [x] `graph-selection-panel.tsx`: provenance, merge dialog, `GraphEdgePopover` for incident edges + create/edit/end
- [x] `entity-merge-dialog.tsx` + `graph-edge-popover.tsx`
- [x] `snapshots-page-client.tsx` + snapshots route UI
- [x] `graph-workspace-panel.tsx` + `workspace-main-grid` integration; `GraphCanvasErrorBoundary` + accessible list + retry
- [x] `note-merge-dialog.tsx`: session stash + **revert survivor fields** after merge; split already creates `extends` link in pipeline
- [x] `pytest` `tests/test_sprint5_graph.py`: overview/subgraph, merge, relationships, empty snapshot, snapshot CRUD
- [x] Docs: `specs/apis.md` (Sprint 5 implemented callout + examples), `README.md` graph section

---

## Sprint review

### Demo readiness

- Graph loads from Postgres canonical store; filters round-trip in the URL.
- Selection panel shows notes, document/page refs, incident relationships, merge, and manual edge flows.
- Snapshots create/list/delete against `graph_snapshots` family.
- `pnpm run build` passes (Next.js 14).

### Gaps / issues

- **Full merge undo** (restoring deleted victim entity / deleted other note) is not implemented — only **revert survivor fields** via PATCH (matches destructive merge semantics in DB).
- `GET …/graph/search` remains future work (not Sprint 5).
- `POST …/snapshots/{id}/review` not implemented in this sprint.

### Next sprint prep

- Sprint 6: chat citation highlights on graph; “Ask about this” wiring.
- Sprint 7: PersistenceJob gate on snapshot delete; external persistence.
