# Sprint 3 — PDF Ingestion

**Duration**: 2 weeks  
**Goal**: End-to-end **document upload**, **PyMuPDF** parsing, **Episode** chunking with page provenance, **IngestionRun** state machine, **SSE** progress per document/job. **FR-1–FR-4**, **US-1.1–US-1.3**, entities `Document`, `IngestionRun`, `Episode` ([datamodel.md](../../specs/datamodel.md)).

## Inputs

- Sprint 2 Cohere + Graphiti initialization (not required for pure parse this sprint, but queue worker infrastructure should align).
- Object storage abstraction: local filesystem bind-mount for P0 ([techstack.md](../../specs/techstack.md)).

## Outputs

- User drops PDF(s); sees per-document status stages: queued → parsing → … (through stages defined in PRD for later sprints, at minimum **parsing** + **queued** + **ready-for-notes** stub OR full pipeline hook point).
- Document list UI with status + timestamps (**FR-2**).
- Episodes queryable via API for a completed parse run.

## Dependencies

- **Sprint 1–2** complete.

---

## Web tier

- [ ] Documents panel: drop zone, multi-file upload (**US-1.2**).
- [ ] `POST /api/v1/workspaces/{id}/documents` multipart → returns document ids + job ids (**apis.md**).
- [ ] Document row UI: status, progress, error surface (**US-1.3**).
- [ ] SSE subscription UI hook (`/jobs/{id}/events` or document-scoped channel per API design).
- [ ] Client-side validation: PDF only, size limit (**FR-1**, **US-1.1** AC).

## Pipeline service

- [ ] Arq (or chosen) worker processes ingestion jobs ([techstack.md](../../specs/techstack.md)).
- [ ] Store file to `storage_uri`; compute **checksum**; enforce unique `(workspace_id, checksum)` (**datamodel.md**).
- [ ] PyMuPDF extract text + **page_count** (**techstack.md**).
- [ ] Chunking strategy with `page_start`/`page_end`, `sequence` (**Episode** fields).
- [ ] Persist **IngestionRun** with `pipeline_version`, `trace_id` (**OpenTelemetry** span optional).
- [ ] Per-chunk failure isolation: retry with backoff (**NFR-6**).
- [ ] Idempotency: `Idempotency-Key` header support on upload (**apis.md** conventions).

## Data + migrations

- [ ] Tables/columns: `documents`, `ingestion_runs`, `episodes` per [datamodel.md](../../specs/datamodel.md).
- [ ] Indexes: `(workspace_id, created_at)`, `(document_id, sequence)`.

## Infra + Docker

- [ ] Volume mount for PDF storage path.
- [ ] Worker service or `pipeline` CMD runs worker process.

## Design + UX

- [ ] Empty state + sample PDF CTA placeholder (wire file in Sprint 8 if not now — note in tasks).

## Docs

- [ ] Operator doc: max upload size env var.

---

## Definition of Done

- [ ] Upload 3 PDFs concurrently; statuses independent (**US-1.2** AC-4).
- [ ] Failed PDF does not corrupt workspace (**FR-4**).
- [ ] Each Episode traces to `document_id` + pages (**datamodel.md**).

## Risks and mitigations

| Risk | Mitigation |
| ---- | ---------- |
| Huge PDFs memory-bound | Stream pages; configurable page batch size |
| Garbled encoding PDFs | Record parse warnings on Document |

## Out of scope

- LLM atomic-note generation (**Sprint 4**).
- Graph entity extraction (**Sprint 4**).

---

## Sprint review (fill at end)

### Demo readiness

### Gaps / issues

### Next sprint prep
