# Sprint 4 — Atomic Notes and Graph Extraction

**Duration**: 2 weeks  
**Goal**: Run **Zettelkasten** atomic-note generation and **Graphiti** entity/relationship extraction from Episodes; persist **`AtomicNote`**, **`NoteLink`**, **`Entity`**, **`Relationship`** with provenance; Notes UI (list + detail + autosave); manual note + manual links; **re-ingest** and **document delete** with cascade options. **FR-5–FR-15**, **US-1.4–US-1.5**, **US-2.1–US-2.6**.

## Inputs

- Parsed Episodes from Sprint 3.
- Graphiti + Cohere from Sprint 2.

## Outputs

- After ingestion completes: populated Notes panel + graph API returns nodes/edges (may still be raw Graphiti-shaped internally — normalize to datamodel IDs).
- User can edit notes, merge/split (UI hooks minimal acceptable if merge/split deferred to Sprint 5 — prefer completing **US-2.3–US-2.4** here if time).

## Dependencies

- **Sprint 3** complete.

---

## Web tier

- [ ] Notes list: search, filters tags/document/origin (**apis.md** GET `/notes`).
- [ ] Note detail: title/body/tags editor, markdown preview, autosave indicator (**US-2.2**).
- [ ] Create manual note (**US-2.5**); distinguish badge (**US-2.5** AC-3).
- [ ] Note linking UI: add/remove links (**US-2.6**).
- [ ] Document detail: ingestion runs timeline + retry from stage (**US-7.1** partial — retry entry).
- [ ] Re-ingest flow UI: `replaces_document_id` (**US-1.4**, **FR-5**).
- [ ] Delete document modal with cascade preview (**US-1.5**, **FR-6**).

## Pipeline service

- [ ] Stage pipeline after parsing: `generating_notes` → `extracting_graph` → `building_graph` → `ready` (**FR-2**, align **Document.status** enum with [datamodel.md](../../specs/datamodel.md)).
- [ ] Prompt templates for atomic notes: one idea per note, citation to episodes/pages (**FR-7–FR-8**).
- [ ] Feed episodes / generated notes into Graphiti for entity & relationship extraction (**FR-12–FR-14**).
- [ ] **Dedup** entities `(workspace_id, type, canonical_name)` (**FR-15**, **datamodel.md** constraints).
- [ ] Persist relational projection: map Graphiti internal IDs ↔ zkast `Entity`/`Relationship` UUIDs (adapter layer).
- [ ] Re-ingest creates new `IngestionRun` + Episodes; does not hard-delete prior graph (**FR-5**).

## Data + migrations

- [ ] Tables: `atomic_notes`, `note_links`, `entities`, `relationships`, junctions for provenance arrays as needed (normalized `note_episodes`, etc.).
- [ ] FK integrity for cascade delete paths (**FR-6**).

## Infra + Docker

- [ ] Tune `SEMAPHORE_LIMIT` for Cohere (**techstack.md** Graphiti note).

## Design + UX

- [ ] Note typography: Crimson Pro `body-lg`, max-width 68ch (**uiux.md**).

## Docs

- [ ] Prompt tuning knobs in workspace settings (defer UI to Sprint 8 if only env-based here).

---

## Definition of Done

- [ ] Single PDF produces multiple atomic notes with `source_episode_ids` (**FR-8**).
- [ ] Graph contains ≥1 entity and ≥1 relationship for fixture PDF.
- [ ] Manual note participates in extraction on next incremental job OR explicit "re-extract" action documented.

## Risks and mitigations

| Risk | Mitigation |
| ---- | ---------- |
| Graphiti ↔ zkast ID mapping bugs | Golden-file integration test on tiny PDF |
| Note quality variance | Allow max-notes-per-doc cap (**FR-8** AC-4) |

## Out of scope

- Force-directed graph canvas (**Sprint 5**).
- Snapshots (**Sprint 5**).

---

## Sprint review (fill at end)

### Demo readiness

### Gaps / issues

### Next sprint prep
