# Sprint 5c — LangExtract Evidence, Typed Graphiti, Filter UX

**Branch**: `sprints/sprint-5c`
**Theme**: Make the graph readable and the filters usable.

## Goals

Three interlocking improvements that fix the root cause of yesterday's
"sea of green dots" graph and the "I don't know my own UUIDs" filter UX:

1. **Type-constrained extraction** — give Graphiti an explicit Pydantic
   entity-type taxonomy so we stop collapsing every node into `"Concept"`.
2. **Source evidence via LangExtract** — co-extract character-level spans
   so the entity detail panel can show "here's the exact PDF passage that
   says this".
3. **Filter UX** — replace every UUID/CSV input in the graph filter bar
   with searchable picklists driven by real data.

Together they make the **Clusters legend** display meaningful colored
groups (because real entity types exist), the **graph filters** usable
without copying UUIDs, and the **entity detail panel** show source
quotes so users can verify what the model claims.

---

## Tasks

### Phase 0 — Paperwork

- [x] Create `sprints/sprint_5c/` + this file
- [x] Branch `sprints/sprint-5c` off `sprints/sprint-5b` (carries forward
      the in-flight polish work)
- [x] Update [`sprints/sprintplan.md`](../sprintplan.md) — add Sprint 5c
      row pointing at this file
- [ ] Add `langextract` and `graphology-communities-louvain` to
      [`specs/techstack.md`](../../specs/techstack.md)  *(deferred to a
      docs sweep; the dependency is already declared in
      `apps/pipeline/requirements.txt` and `apps/web/package.json`)*

### Phase 1 — Typed entity extraction (Graphiti)

- [x] New module `apps/pipeline/app/entity_schemas.py` — Pydantic models
      for the canonical type set:
      - `Person` (full_name, role, affiliation)
      - `Organization` (full_name, kind: agency / company / consortium)
      - `Location` (name, geo_scope: facility / region / country)
      - `Document` (title, doc_type: standard / report / regulation)
      - `Standard` (identifier, issuing_org, version)
      - `Equipment` (name, manufacturer, generation)
      - `Process` (name, domain)
      - `Material` (name, composition)
      - `Event` (name, when)
      - `Concept` (name) — generic fallback
- [x] Pass `entity_types=<dict>` to `graphiti.add_episode(...)` in
      [`apps/pipeline/app/tasks.py`](../../apps/pipeline/app/tasks.py)
      (`extract_graph` and the note-processing path)
- [x] Pass `edge_types=<dict>` too, with the common relations:
      `WORKS_FOR`, `LOCATED_IN`, `PUBLISHED`, `CITES`, `MANAGES`,
      `INSPECTS`, `MITIGATES`, `RELATES_TO` (fallback)
- [x] Migration `0008_typed_entities.py` — **NOT NEEDED**: existing
      schema (`entities.type TEXT`, `entities.properties JSONB`)
      already supports typed entities. The existing
      `entity_type_from_labels` picks the first non-`Entity` label, so
      typed extraction flows through unchanged.
- [x] Update `entities_repo.upsert_entity_from_graphiti` — **NOT
      NEEDED**: it already persists `attributes` into `properties`.
- [x] Tests:
      - [x] `tests/test_typed_entities.py` — 7 tests covering schema
            registration, Pydantic types, docstrings, edge type map
            validation, required-field enforcement, and `add_episode`
            kwargs wiring.
      - [x] Existing tests still green (verified on host).

### Phase 2 — LangExtract co-extractor + evidence table

- [x] Add `langextract>=1.0,<2` to
      [`apps/pipeline/requirements.txt`](../../apps/pipeline/requirements.txt)
- [x] New module `apps/pipeline/app/evidence_extractor.py` — schema-
      guided LangExtract via OpenAI provider pointed at Cohere's
      `compatibility/v1`; returns `EvidenceSpan(name, type, char_start,
      char_end, quote, attributes)`; all failure modes (empty, timeout,
      exception) return `[]` so evidence never blocks the run.
- [x] Migration **renumbered to `0008_entity_evidence`** (since the
      Phase 1 migration was unneeded) — table with FKs to workspaces /
      entities / documents / episodes, CHECK `char_end >= char_start`,
      indexes on `(entity_id, created_at)` and `(document_id, page)`.
- [x] New repo `apps/pipeline/app/evidence_repo.py` —
      `insert_evidence_rows`, `list_evidence_for_entity`,
      `count_evidence_for_document`, `delete_evidence_for_document`.
- [x] Wire into `tasks.py:extract_graph` — per-episode, build an
      `entity_index` from the Graphiti upsert pass, call
      `extract_evidence_spans` + `link_spans_to_entities`, bulk-insert.
      New counters `evidence_extracted` / `evidence_linked` flow into
      the JobLogConsole log + metric events.
- [x] Tests — `tests/test_evidence_extractor.py` (12 tests covering
      name normalization, taxonomy filtering, char-interval fallback,
      unfindable-span drop, exact + type-agnostic linking, empty input,
      error non-fatality, timeout fallback, page_for_offset).

### Phase 3 — Evidence in the entity detail panel

- [x] New endpoint:
      `GET /internal/v1/workspaces/{ws}/graph/entities/{entityId}/evidence`
      ([`apps/pipeline/app/internal_graph.py`](../../apps/pipeline/app/internal_graph.py))
- [x] Web proxy at
      `apps/web/src/app/api/v1/workspaces/[workspaceId]/graph/entities/[entityId]/evidence/route.ts`
- [x] New `EvidenceSection` in
      [`apps/web/src/components/graph-selection-panel.tsx`](../../apps/web/src/components/graph-selection-panel.tsx)
      — each row shows page number, blockquote, document filename, and a
      "View in document" link that navigates to
      `/documents/<id>?page=<n>&highlight=<offset>`
- [ ] Document detail panel: honor `?page` + `?highlight` by scrolling
      the PDF preview to the page and highlighting the character range
      *(deferred to Sprint 7 — link navigates correctly today)*
- [ ] Update [`specs/apis.md`](../../specs/apis.md) and
      [`specs/uiux.md`](../../specs/uiux.md)  *(deferred to a docs sweep)*

### Phase 4 — Filter UX overhaul ✅

Replace every UUID/CSV input in
[`apps/web/src/components/graph-filter-bar.tsx`](../../apps/web/src/components/graph-filter-bar.tsx)
with components that load real data.

- [x] `GET /internal/v1/workspaces/{ws}/graph/types`
- [x] `GET /internal/v1/workspaces/{ws}/notes/tags`
- [x] `GET /internal/v1/workspaces/{ws}/graph/entities/search-typeahead?q=`
- [x] Web proxies for each new endpoint
- [x] New components in `apps/web/src/components/filters/`:
      - [x] `document-picker.tsx`
      - [x] `entity-typeahead.tsx`
      - [x] `type-multiselect.tsx` (handles both entity + edge types)
      - [x] `tag-picker.tsx` (with free-text fallback)
- [x] Rewire `graph-filter-bar.tsx` — query-string contracts preserved
- [x] Accessibility — ARIA combobox roles, keyboard ↑/↓/Enter/Esc, focus-visible rings
- [x] Visual — uses existing tokens; empty states inline (no toast needed)

### Phase 5 — Tests, docs, closeout

- [x] Pipeline tests pass — 19/19 on host (Phase 1: 7, Phase 2: 12).
- [x] Web typecheck clean — `tsc --noEmit` exit 0.
- [ ] New web RTL tests for the four pickers — **deferred to TD-013**:
      the project doesn't have RTL/jest set up; introducing it is
      better as its own sprint of work.
- [x] [`sprintplan.md`](../sprintplan.md) updated with Sprint 5c row
- [ ] Update [`specs/apis.md`](../../specs/apis.md), README —
      deferred to a docs sweep PR.
- [ ] Backfill plan / script for re-extracting evidence on docs
      ingested before Sprint 5c — deferred (user can simply use the
      existing "Retry from extracting_graph" UI on each doc).
- [x] Wrote [`sprints/sprint_5c/sprint_5c_report.md`](sprint_5c_report.md)
- [x] Commit + push `sprints/sprint-5c`; do not merge (user reviews)

---

## Definition of done

- Graph legend shows ≥ 5 distinct entity types for a 20-page mixed PDF
  (instead of 100% Concept).
- Clicking any entity opens an "Evidence" tab with at least one PDF
  passage quote per Graphiti-extracted entity.
- The graph filter bar has zero free-form UUID fields; every selector
  is a combobox / multi-select / chip group backed by real data.
- All new pipeline tests pass.
- `pnpm --filter web build` is clean.

## Out of scope (defer to Sprint 6 or beyond)

- Swapping out Graphiti for PropertyGraphIndex / GraphRAG (TD-013, future).
- Highlighting character ranges *inside* the rendered PDF preview —
  Phase 3 scrolls to page; precise span highlighting is a Sprint 7 item.
- Triplex / GLiNER local-extractor experiments (backlog).
- Re-running ingestion automatically when an entity-type taxonomy
  changes (manual retry from doc detail panel is sufficient for now).

## References

- Skill: [ui-ux-pro-max](../../.cursor/skills/ui-ux-pro-max/SKILL.md)
- LangExtract: https://github.com/google/langextract
- Graphiti custom types:
  https://github.com/getzep/graphiti/blob/main/docs/custom_entity_types.md
- TD-010 (Graphiti edge-timestamp 400 storm) in
  [tech_debt.md](../tech_debt.md) — unblocked side benefit: with
  typed extraction the per-edge timestamp call may stop tripping
  Cohere's `json_schema` validator.
