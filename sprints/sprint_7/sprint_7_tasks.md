# Sprint 7 — Chat UX and External Persistence

**Duration**: 2 weeks  
**Goal**: Ship **Chat Home**, **Chat View**, **Chat Drawer** per [uiux.md](../../specs/uiux.md); scope picker (documents/tags/types/snapshot pin); citation hover/popover + click-through to notes/PDF; retrieval inspector; **regenerate** + alternates; **"Ask about this"** from graph/notes (**FR-44**, **US-8.3**, **US-8.5–US-8.7**). Implement **ExternalGraphTarget** CRUD + connection test + **PersistenceJob** with dry-run, **upsert** default, **replace** with confirmation (**FR-23–FR-28**, **US-4.1–US-4.3**).

## Inputs

- Chat core from Sprint 6.
- Snapshots from Sprint 5.
- External-graph contract ([datamodel.md](../../specs/datamodel.md) External-Graph Contract).

## Outputs

- Product-demo-ready chat UX alongside graph.
- User persists snapshot to Neo4j or Postgres+AGE; job progress + cancel (**FR-26**, **US-4.2**).

## Dependencies

- **Sprint 6** complete.

---

## Web tier

- [ ] Chat Home list + filters (**uiux.md** Chat Home).
- [ ] Chat View + Composer + Stop + coverage footer (**uiux.md** Chat Surface).
- [ ] Chat Drawer in workspace layout (**uiux.md** four layout modes).
- [ ] Scope controls + header chips (**US-8.3**).
- [ ] Citation chips: hover, keyboard focus, navigation to note/doc page (**US-8.2**).
- [ ] Alternates strip + select active (**US-8.6**).
- [ ] "Ask about this" actions (**US-8.7**, **apis.md** `seed_context`).
- [ ] Targets UI: add/edit/test/delete (**US-4.1**).
- [ ] Persistence UI: dry-run → confirmation token → job monitor (**apis.md**, **US-4.2–US-4.3**).

## Pipeline service

- [ ] Neo4j writer: upsert by `(zkast_workspace_id, zkast_id)`; create constraints (**datamodel.md**).
- [ ] AGE writer: parallel mapping using openCypher subset (**NFR-8**).
- [ ] Optional provenance subgraph job flag (**datamodel.md**).
- [ ] Replace mode: diff counts from dry-run (**FR-27**).

## Data + migrations

- [ ] Tables: `external_graph_targets`, `persistence_jobs`, extend `api_keys` for `target_neo4j`, `target_age`.
- [ ] Store connection metadata without secrets (**datamodel.md** `ExternalGraphTarget`).

## Infra + Docker

- [ ] Document optional sidecar Neo4j + AGE for local persistence testing (operator-owned targets).

## Design + UX

- [ ] Full citation + retrieval inspector compliance with **UI Implementation Acceptance Checklist** ([uiux.md](../../specs/uiux.md)).

## Docs

- [ ] Operator guide: Neo4j permissions needed for constraint creation (**datamodel.md** Constraints Required).

---

## Definition of Done

- [ ] Persist snapshot → counts reported + warnings visible (**US-4.2** AC-3).
- [ ] Default upsert never deletes extraneous graph data (**US-4.3** AC-1).
- [ ] Chat scope pinned to snapshot yields reproducible retrieval (**US-8.3** AC-4).

## Risks and mitigations

| Risk | Mitigation |
| ---- | ---------- |
| AGE vs Neo4j feature gaps | Stay inside shared contract only |
| Secret leakage in logs | Redaction middleware + audit |

## Out of scope

- Chat export Markdown (**P1** US-8.10).
- Workspace sharing sessions (**P1** US-8.11).

---

## Sprint review (fill at end)

### Demo readiness

### Gaps / issues

### Next sprint prep
