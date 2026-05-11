# Sprint 5 — Graph Visualization and Editing

**Duration**: 2 weeks  
**Goal**: Interactive **Graph Panel** (`react-force-graph` WebGL) with entity-type colors + **shape markers** ([uiux.md](../../specs/uiux.md)), filters, selection + provenance panel, CRUD on entities/relationships from graph context, **merge/split notes** from Sprint 4 if not finished, **hybrid search** via Graphiti, **Accessible Graph View** list fallback, **GraphSnapshot** create. **FR-17–FR-22**, **US-2.3–US-2.4**, **US-3.1–US-3.6**.

## Inputs

- Populated entities/relationships/notes from Sprint 4.

## Outputs

- Three-panel workspace: selecting document filters notes + graph (**uiux.md** cross-panel selection).
- User creates named snapshot; snapshots listed (**US-3.6**, **FR-22**).

## Dependencies

- **Sprint 4** complete.

---

## Web tier

- [ ] `GET /graph` client: fetch subgraph with filters + node caps (**apis.md**, **NFR-4** truncation banner).
- [ ] Implement **react-force-graph** canvas + mini-map + legend (**US-3.1**).
- [ ] Filter bar: entity types, edge types, document, tags, time (**US-3.2**).
- [ ] Selection panel: provenance drill-down to notes/docs (**US-3.3**).
- [ ] Entity rename/merge/delete; edge add/edit/end-validity (**US-3.4–US-3.5**, **FR-20–FR-21**).
- [ ] Accessible Graph View toggle: keyboard navigable list (**uiux.md**, **US-3.1** AC accessibility).
- [ ] Command surface preparation for Sprint 8 (optional stub).
- [ ] Snapshot creation modal (**US-3.6**).

## Pipeline service

- [ ] Graph search endpoint proxying Graphiti hybrid search (**apis.md** `GET /graph/search`).
- [ ] Batch endpoints or efficient SQL for graph payload assembly.

## Data + migrations

- [ ] `graph_snapshots` table + immutable snapshot payload strategy (store ID sets + frozen JSON blobs per [datamodel.md](../../specs/datamodel.md)).

## Infra + Docker

- [ ] Memory flags for WebGL in dockerized browsers — document host GPU expectations.

## Design + UX

- [ ] Apply entity palette table + edge opacity rules (**uiux.md** Visual Design System).
- [ ] Shape markers for nodes (circle vs hexagon implementation via sprite or SVG texture).

## Docs

- [ ] Performance tuning: default `node_limit` vs hardware.

---

## Definition of Done

- [ ] Pan/zoom/select usable at **60fps** for **5k nodes / 15k edges** on target laptop (**NFR-4**) OR show truncation + Accessible fallback path documented if hardware fails.
- [ ] Filters compose AND semantics (**US-3.2** AC-2).
- [ ] Snapshot created is immutable (**FR-22** AC-3).

## Risks and mitigations

| Risk | Mitigation |
| ---- | ---------- |
| WebGL perf cliffs | Aggressive level-of-detail + optional Cytoscape fallback (**techstack.md**) |
| URL bookmark for filters | Sync filter state to query string (**US-3.2** AC-3) |

## Out of scope

- Grounded chat (**Sprint 6–7**).
- External persistence (**Sprint 7**).

---

## Sprint review (fill at end)

### Demo readiness

### Gaps / issues

### Next sprint prep
