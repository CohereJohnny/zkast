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

- [ ] Create `sprints/sprint_5c/` + this file
- [ ] Branch `sprints/sprint-5c` off `sprints/sprint-5b` (carries forward
      the in-flight polish work)
- [ ] Update [`sprints/sprintplan.md`](../sprintplan.md) — add Sprint 5c
      row pointing at this file
- [ ] Add `langextract` and `graphology-communities-louvain` to
      [`specs/techstack.md`](../../specs/techstack.md)

### Phase 1 — Typed entity extraction (Graphiti)

- [ ] New module `apps/pipeline/app/entity_schemas.py` — Pydantic models
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
- [ ] Pass `entity_types=<dict>` to `graphiti.add_episode(...)` in
      [`apps/pipeline/app/tasks.py`](../../apps/pipeline/app/tasks.py)
      (`extract_graph` and the note-processing path)
- [ ] Pass `edge_types=<dict>` too, with the common relations:
      `WORKS_FOR`, `LOCATED_IN`, `PUBLISHED`, `CITES`, `MANAGES`,
      `INSPECTS`, `MITIGATES`, `RELATES_TO` (fallback)
- [ ] Migration `0008_typed_entities.py`:
      - Relax `entities.entity_type` enum to a free-form text column
        with an index (so future types don't require a migration)
      - Add `entities.attributes JSONB` so typed-attribute payloads
        survive the canonical mirror
- [ ] Update `entities_repo.upsert_entity_from_graphiti` to persist the
      attribute dict
- [ ] Tests:
      - [ ] `tests/test_typed_entities.py` — assert `add_episode` is
            called with the entity_types kwarg + the Pydantic models
            serialize cleanly
      - [ ] Existing tests still green (`pytest -k entities`)

### Phase 2 — LangExtract co-extractor + evidence table

- [ ] Add `langextract>=1.0.0` to
      [`apps/pipeline/requirements.txt`](../../apps/pipeline/requirements.txt)
- [ ] New module `apps/pipeline/app/evidence_extractor.py`:
      - Schema-guided LangExtract prompt covering the same entity types
        as Phase 1
      - Per-episode async extraction returning
        `[{name, type, char_start, char_end, page, quote}]`
      - Defaults to Cohere via `OPENAI_API_BASE` shim; falls back to
        `GEMINI_API_KEY` when set (LangExtract's native path)
      - Timeouts + retry sharing the same backoff helper as
        `cohere_adapters.py`
- [ ] Migration `0009_entity_evidence.py`:
      - `entity_evidence(id, entity_id FK, document_id FK, episode_id FK,
        page INT, char_start INT, char_end INT, quote TEXT,
        created_at TIMESTAMPTZ)`
      - Indexes on `(entity_id)`, `(document_id, page)`
- [ ] New repo `apps/pipeline/app/evidence_repo.py`:
      - `insert_evidence_rows(...)`
      - `list_evidence_for_entity(workspace_id, entity_id, limit)`
      - `count_evidence_for_document(document_id)`
- [ ] Wire into `tasks.py:extract_graph`:
      - Run LangExtract in parallel with Graphiti per episode (under the
        same `Semaphore`)
      - After Graphiti returns, fuzzy-match LangExtract spans to entities
        by `(name_normalized, type)` and `insert_evidence_rows`
      - Emit metrics: `evidence_spans_extracted`, `evidence_spans_linked`
        for the JobLogConsole
- [ ] Tests:
      - [ ] `tests/test_evidence_extractor.py` — mocked LangExtract;
            empty response and error both non-fatal to the run
      - [ ] `tests/test_evidence_linking.py` — fuzzy match handles
            simple name variations ("MRP-227" ↔ "MRP 227")

### Phase 3 — Evidence in the entity detail panel

- [ ] New endpoint:
      `GET /internal/v1/workspaces/{ws}/graph/entities/{entityId}/evidence`
      → paged `{ items: [{ page, quote, document_id, document_filename,
      char_start, char_end }], total }`
      ([`apps/pipeline/app/internal_graph.py`](../../apps/pipeline/app/internal_graph.py))
- [ ] Web proxy at
      `apps/web/src/app/api/v1/workspaces/[workspaceId]/graph/entities/[entityId]/evidence/route.ts`
- [ ] New tab "Evidence" in
      [`apps/web/src/components/graph-selection-panel.tsx`](../../apps/web/src/components/graph-selection-panel.tsx)
      — each row shows page number, blockquote, document filename, and a
      "View in document" button that navigates to
      `/documents/<id>?page=<n>&highlight=<offset>`
- [ ] Document detail panel: honor `?page` + `?highlight` by scrolling
      the PDF preview to the page and highlighting the character range
- [ ] Update [`specs/apis.md`](../../specs/apis.md) and
      [`specs/uiux.md`](../../specs/uiux.md)

### Phase 4 — Filter UX overhaul

Replace every UUID/CSV input in
[`apps/web/src/components/graph-filter-bar.tsx`](../../apps/web/src/components/graph-filter-bar.tsx)
with components that load real data.

- [ ] New endpoint:
      `GET /internal/v1/workspaces/{ws}/graph/types` →
      `{ entity_types: [{ name, count }], edge_types: [{ name, count }] }`
      (counts present in the current workspace's graph)
- [ ] New endpoint:
      `GET /internal/v1/workspaces/{ws}/notes/tags` →
      `{ tags: [{ name, count }] }`
- [ ] New endpoint:
      `GET /internal/v1/workspaces/{ws}/graph/entities/search?q=<text>` —
      typeahead for seed-entity selection (re-uses existing
      `/graph/search` Graphiti route; new wrapper returns `id`, `name`,
      `type`, `degree`)
- [ ] Web proxies for each new endpoint
- [ ] New components in `apps/web/src/components/filters/`:
      - [ ] `document-picker.tsx` — combobox over ready documents
            (label = filename + page count, value = id, search by
            filename); pulls from existing
            `/workspaces/{ws}/documents?status=ready`
      - [ ] `entity-typeahead.tsx` — multi-select with debounced
            search; chip-style selected items show entity name + type
            color; backed by the new entity search endpoint
      - [ ] `type-multiselect.tsx` — chip group; option list from
            `/graph/types`; each chip shows count
      - [ ] `tag-picker.tsx` — combobox over `/notes/tags`
- [ ] Rewire `graph-filter-bar.tsx` to use the new components; preserve
      all existing query-string contracts (`document_id`,
      `seed_entity_ids`, `tag`, `entity_types`, `edge_types`)
- [ ] Accessibility: each combobox follows the ARIA combobox pattern
      (text input + listbox + selected-options region), keyboard nav
      (↑/↓/Enter/Esc/Backspace-to-remove), focus visible
- [ ] Visual: match the existing card / chip tokens (no new colors); use
      `useFeedback` for "no documents yet" empty states

### Phase 5 — Tests, docs, closeout

- [ ] Pipeline tests pass (`pytest apps/pipeline/tests`)
- [ ] Web tests pass (`pnpm --filter web build`, `pnpm --filter web lint`)
- [ ] New web tests:
      - [ ] `apps/web/src/components/filters/__tests__/document-picker.test.tsx`
      - [ ] `apps/web/src/components/filters/__tests__/entity-typeahead.test.tsx`
- [ ] Update [`specs/apis.md`](../../specs/apis.md), README, and
      [`sprints/sprintplan.md`](../sprintplan.md) (mark Sprint 5c row)
- [ ] Backfill plan: document how to re-extract evidence for documents
      already ingested before Sprint 5c (one-shot script
      `apps/pipeline/scripts/backfill_evidence.py`)
- [ ] Write `sprints/sprint_5c/sprint_5c_report.md`
- [ ] Commit + push `sprints/sprint-5c`; do not merge (user reviews)

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
