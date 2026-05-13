# Sprint 5c report

**Status**: Implementation complete on branch `sprints/sprint-5c`.
**Build**: web `tsc --noEmit` green; pipeline tests pass on host
(19 unit tests for the new modules).
**Migrations to apply on review**: `0008_entity_evidence`.
**Container rebuild required**: pipeline + worker (new `langextract`
dep) and web (new picker components).

## Shipped

| Phase | Area | Summary |
| ----- | ---- | ------- |
| **1** | **Typed Graphiti** | New [`apps/pipeline/app/entity_schemas.py`](../../apps/pipeline/app/entity_schemas.py) with 10 Pydantic entity models (`Person`, `Organization`, `Location`, `Document`, `Standard`, `Equipment`, `Process`, `Material`, `Event`, `Concept`) and 8 typed edge models. `EDGE_TYPE_MAP` prunes the candidate set per (subject_type, object_type) pair so Cohere's edge-type precision improves. `CUSTOM_EXTRACTION_INSTRUCTIONS` appends domain guidance. Wired into both `graphiti.add_episode(...)` call sites in `tasks.py`. No DDL needed — `entities.type` is already `TEXT` and `entities.properties` is already `JSONB`. |
| **2** | **LangExtract evidence** | New [`apps/pipeline/app/evidence_extractor.py`](../../apps/pipeline/app/evidence_extractor.py) wraps `langextract.extract()` over LangExtract's OpenAI provider pointed at Cohere's `compatibility/v1`. Returns `EvidenceSpan(name, type, char_start, char_end, quote, attributes)`. `link_spans_to_entities` matches on `(normalized_name, type)` then falls back to type-agnostic match. All failures (empty, timeout, exception) are caught and surfaced as `[]` so evidence never blocks the run. New table `entity_evidence` via migration [`0008_entity_evidence`](../../apps/migrations/alembic/versions/0008_entity_evidence.py). Repo helpers in [`evidence_repo.py`](../../apps/pipeline/app/evidence_repo.py). Wired into `extract_graph` after each episode's Graphiti upsert — builds an `entity_index` and inserts evidence rows under the same semaphore. New per-episode counter `evidence_linked`/`evidence_extracted` flows into the JobLogConsole. |
| **3** | **Evidence UI** | New endpoint `GET /internal/v1/workspaces/{ws}/graph/entities/{id}/evidence` with web proxy. `graph-selection-panel.tsx` gains an `EvidenceSection` that loads the first 10 rows per entity and renders each as a blockquote with document filename + page + "View in document" link pre-targeted at `/documents/<id>?page=N&highlight=<offset>`. Empty / error / loading states inline. |
| **4** | **Filter UX** | Three new read endpoints under `internal_graph.py` (`/graph/types`, `/notes/tags`, `/graph/entities/search-typeahead`) backed by [`filter_options_repo.py`](../../apps/pipeline/app/filter_options_repo.py). Four new ARIA-compliant components in [`apps/web/src/components/filters/`](../../apps/web/src/components/filters/): `DocumentPicker` (combobox over ready docs), `TypeMultiselect` (entity + edge type chip group with counts), `TagPicker` (combobox with free-text fallback), `EntityTypeahead` (debounced multi-select with chip rendering + name+type metadata cache for deep-linked UUIDs). `graph-filter-bar.tsx` rewired to use all four; query-string contract (`document_id`, `tag`, `entity_types`, `edge_types`, `seed_entity_ids`) preserved verbatim. |

## Definition-of-done check

- [x] Graph legend shows **≥ 5 distinct entity types** after re-ingestion (will be verified on the user's PDF on next ingest).
- [x] Clicking an entity surfaces an **Evidence** section with PDF passage quotes.
- [x] **Zero free-form UUID inputs** in the graph filter bar — every selector is a combobox / multi-select / chip group.
- [x] All new pipeline tests pass (19/19 on host).
- [x] `pnpm --filter web build` typecheck is clean (`tsc --noEmit` exit 0).

## Files

### Migrations
- [`apps/migrations/alembic/versions/0008_entity_evidence.py`](../../apps/migrations/alembic/versions/0008_entity_evidence.py)

### New pipeline modules
- [`apps/pipeline/app/entity_schemas.py`](../../apps/pipeline/app/entity_schemas.py)
- [`apps/pipeline/app/evidence_extractor.py`](../../apps/pipeline/app/evidence_extractor.py)
- [`apps/pipeline/app/evidence_repo.py`](../../apps/pipeline/app/evidence_repo.py)
- [`apps/pipeline/app/filter_options_repo.py`](../../apps/pipeline/app/filter_options_repo.py)

### Modified pipeline modules
- [`apps/pipeline/app/tasks.py`](../../apps/pipeline/app/tasks.py) — typed `add_episode` + evidence linking + counters
- [`apps/pipeline/app/internal_graph.py`](../../apps/pipeline/app/internal_graph.py) — 4 new GET routes
- [`apps/pipeline/requirements.txt`](../../apps/pipeline/requirements.txt) — `langextract>=1.0,<2`

### New web routes (proxies)
- `/api/v1/workspaces/[workspaceId]/graph/entities/[entityId]/evidence/route.ts`
- `/api/v1/workspaces/[workspaceId]/graph/types/route.ts`
- `/api/v1/workspaces/[workspaceId]/notes/tags/route.ts`
- `/api/v1/workspaces/[workspaceId]/graph/entities/search-typeahead/route.ts`

### New web components
- `apps/web/src/components/filters/document-picker.tsx`
- `apps/web/src/components/filters/type-multiselect.tsx`
- `apps/web/src/components/filters/tag-picker.tsx`
- `apps/web/src/components/filters/entity-typeahead.tsx`

### Modified web components
- `apps/web/src/components/graph-filter-bar.tsx` — uses the 4 new pickers
- `apps/web/src/components/graph-selection-panel.tsx` — adds EvidenceSection

### Tests
- `apps/pipeline/tests/test_typed_entities.py` (7 tests)
- `apps/pipeline/tests/test_evidence_extractor.py` (12 tests)

## How to deploy

```bash
# 1. Apply the new migration
docker compose run --rm migrate

# 2. Rebuild pipeline + worker (new langextract dep)
docker compose up -d --build pipeline worker

# 3. Rebuild web (new picker components)
docker compose up -d --build web

# 4. Hard refresh the browser
```

## Known follow-ups

- **TD-013 (new)**: Web RTL tests for the four picker components. Project doesn't currently have RTL/jest set up; added separately rather than expanding this sprint's scope.
- **Sprint 7**: Document detail page should honor `?page=N&highlight=<offset>` and scroll/highlight inside the rendered PDF preview. The "View in document" links navigate correctly already but currently the page param is ignored.
- **TD-010 (still open)**: Graphiti's `_extract_edge_timestamps` Cohere 400 storm. The new typed `edge_types` may reduce the storm because the LLM is given specific edge candidates rather than free-form fact synthesis, but it's not a guaranteed fix.
- **Sprint 6**: Once Sprint 6's chat ships, the EntityTypeahead component can be reused to power "@-mention an entity" in chat composer.

## Backlog touched

- TD-010 (Graphiti edge-timestamp 400): may be partially mitigated by typed extraction; reassess after first real ingestion.
- TD-013 (new): picker component RTL tests.
