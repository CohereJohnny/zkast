# zkast — User Stories

User stories grouped by epic. Each story uses the form **As a [persona], I want [capability], so that [outcome]** and includes acceptance criteria. Stories are tagged with the phase they target: **P0** (self-hosted single-user MVP), **P1** (self-hosted multi-user), **P2** (SaaS).

Persona IDs (P-1 .. P-5) reference [personas.md](personas.md). Requirement IDs (FR-*, NFR-*) reference [prd.md](prd.md).

## Epic 1 — Document Ingestion

### US-1.1 — Upload a single PDF (P0)

**As** Maya the Researcher (P-1), **I want** to drag a PDF onto the zkast window, **so that** I can start turning it into atomic notes.

**Acceptance criteria**:

- AC-1: Dropping a single PDF on the upload zone immediately creates a Document record in "queued" status.
- AC-2: The Document appears in the Documents panel within 500 ms of drop.
- AC-3: Files over the configured size limit (default 50 MB) are rejected with a clear error before upload starts.
- AC-4: Non-PDF files are rejected with a clear error.
- AC-5: The user does not need to refresh the page to see processing state updates.

Satisfies: FR-1, FR-2.

### US-1.2 — Upload many PDFs at once (P0)

**As** Dev the PhD Student (P-2), **I want** to select an entire folder of PDFs and upload them all, **so that** I can ingest my thesis corpus in one sitting.

**Acceptance criteria**:

- AC-1: Selecting or dropping multiple files creates one Document per file, each in "queued" status.
- AC-2: Ingestion is rate-limited per workspace so the LLM provider's quota is not blown.
- AC-3: The user sees per-document status and an aggregate progress indicator.
- AC-4: A failed Document does not block the others.

Satisfies: FR-1, FR-2, FR-4.

### US-1.3 — See ingestion progress with stages (P0)

**As** any user, **I want** to see which pipeline stage each document is in (queued, parsing, generating notes, extracting graph, building graph, ready, failed), **so that** I can tell whether progress is being made or something is stuck.

**Acceptance criteria**:

- AC-1: Each Document shows its current stage and a timestamp for the last stage transition.
- AC-2: A failed Document shows the failing stage and a short, human-readable error.
- AC-3: Clicking the status reveals stage timing and (in multi-user mode) the OTEL trace ID.

Satisfies: FR-2, NFR-7.

### US-1.4 — Re-ingest an updated PDF (P0)

**As** Maya (P-1), **I want** to upload a newer version of a PDF I already ingested, **so that** my graph reflects the updated document without losing the previous version's history.

**Acceptance criteria**:

- AC-1: The user can mark a new upload as "replaces document X."
- AC-2: Re-ingestion creates a new IngestionRun and new Episodes; previous Episodes are preserved.
- AC-3: The user is told how many existing atomic notes / entities / edges will be affected before they confirm.
- AC-4: A new GraphSnapshot is created on completion; the previous snapshot remains queryable.

Satisfies: FR-5, FR-14.

### US-1.5 — Delete a document and clean up derived data (P0)

**As** Maya (P-1), **I want** to delete a Document and choose whether to also delete its derived notes, entities, and edges, **so that** I can correct mistakes without orphaning data.

**Acceptance criteria**:

- AC-1: Deletion shows a preview of: notes that trace only to this document, notes shared with other documents, entities/edges that would lose all provenance.
- AC-2: The user can choose: delete document only, delete document + exclusive derivatives, or cancel.
- AC-3: No data is removed from any external graph DB target as part of this operation.

Satisfies: FR-6, FR-14.

## Epic 2 — Atomic Note Authoring (Zettelkasten)

### US-2.1 — Auto-generate atomic notes from a document (P0)

**As** Maya (P-1), **I want** the LLM to convert each document into atomic, Zettelkasten-compliant notes, **so that** I do not have to write them by hand.

**Acceptance criteria**:

- AC-1: Each generated note expresses a single idea.
- AC-2: Each note has a title, body, source citation (document + page range), tags, and at least one suggested link to a related note (when one exists).
- AC-3: Every note traces back to one or more source Episodes (chunks).
- AC-4: Generation is bounded by a workspace-configurable maximum notes per document.

Satisfies: FR-7, FR-8, FR-14.

### US-2.2 — Read and edit an atomic note (P0)

**As** any user, **I want** to read a note and edit any of its fields, **so that** I can correct LLM mistakes and add my own thinking.

**Acceptance criteria**:

- AC-1: Title, body, and tags are all editable in a single note view.
- AC-2: Edits are saved automatically with a visible "saved" indicator.
- AC-3: Edited notes are marked as user-edited and their source citation is preserved unless the user explicitly clears it.

Satisfies: FR-9.

### US-2.3 — Merge two notes (P0)

**As** Maya (P-1), **I want** to merge two notes that are saying the same thing, **so that** the graph does not have duplicate ideas.

**Acceptance criteria**:

- AC-1: The user selects two notes and chooses "Merge."
- AC-2: The user picks which fields come from which source; provenance is unioned automatically.
- AC-3: All inbound links to either source note are rewritten to the merged note.
- AC-4: A merge can be reversed at any time via persisted **Full undo** (restores the victim note and its provenance from `merge_audit_log`) or **Revert survivor fields** (rolls back only the survivor's mutable fields). Undo remains available indefinitely until the survivor row is deleted; there is no "current session only" restriction.

Satisfies: FR-9. Sprint 5b shipped the persisted-undo affordance via `POST .../notes/{id}/unmerge`.

### US-2.4 — Split a note (P0)

**As** Dev (P-2), **I want** to split a note that the LLM made too broad into two atomic notes, **so that** the Zettelkasten principle of atomicity is preserved.

**Acceptance criteria**:

- AC-1: The user selects a passage in the body and chooses "Split into new note."
- AC-2: The new note inherits the source citation of the parent for the selected passage.
- AC-3: A link is automatically created between the parent and new note.

Satisfies: FR-9.

### US-2.5 — Create a manual note not derived from any document (P0)

**As** Maya (P-1), **I want** to write my own atomic note from scratch, **so that** I can capture my own ideas alongside the imported ones.

**Acceptance criteria**:

- AC-1: A "New note" action creates a note with no document provenance.
- AC-2: The note participates fully in linking, tagging, and graph extraction.
- AC-3: The note is visually distinguishable from LLM-generated notes (e.g., a "manual" badge).

Satisfies: FR-10.

### US-2.6 — Link or unlink two notes manually (P0)

**As** any user, **I want** to add or remove a link between two notes manually, **so that** I can curate connections the LLM did not propose.

**Acceptance criteria**:

- AC-1: A note view shows all current links and offers an "Add link" action with note search.
- AC-2: Removing a link removes only that link; it does not delete either note.

Satisfies: FR-11.

### US-2.7 — View the source PDF passage that produced an entity (P0)

**As** Maya (P-1), **I want** to click any entity in the graph and see the exact passage from the source PDF that the extractor used to create it, **so that** I can verify the model's claims without leaving the app and trust the graph as audit-able.

**Acceptance criteria**:

- AC-1: The entity selection panel shows an `Evidence` section listing per-entity character-offset spans linked to documents and pages.
- AC-2: Each evidence row renders the source document filename, page number, and a blockquote of the verbatim quote (≤ 600 chars).
- AC-3: A "View in document" link on each row navigates to `/documents/<id>?page=N&highlight=<char_start>`. The document detail view honors the page param to scroll the PDF preview to that page; precise span highlighting is a Sprint 7 polish.
- AC-4: When no evidence rows exist (entity predates the LangExtract co-extractor), the section shows a friendly empty state pointing to "Retry from extracting_graph" rather than appearing broken.
- AC-5: Re-ingestion or "Retry from extracting_graph" repopulates evidence rows for that document; deleting the document cascade-deletes the related evidence.

Satisfies: FR-14 (provenance) and a new product affordance for source grounding. Sprint 5c shipped the `entity_evidence` table, the `GET .../graph/entities/{id}/evidence` endpoint, and the EvidenceSection UI.

## Epic 3 — Knowledge Graph Review

### US-3.1 — Visualize the working graph (P0)

**As** Maya (P-1), **I want** to see an interactive force-directed graph of my workspace, **so that** I can navigate by visual association the way I do in Obsidian.

**Acceptance criteria**:

- AC-1: The graph panel renders all entities and edges in the current workspace's working graph.
- AC-2: Pan, zoom, and selection remain smooth at 60fps for graphs up to 5,000 nodes / 15,000 edges on a 2020-era laptop.
- AC-3: Different entity types and edge types are visually distinguishable.

Satisfies: FR-17, NFR-4.

### US-3.2 — Filter the graph (P0)

**As** Dev (P-2), **I want** to filter the graph by document, tag, entity type, edge type, seed entities, or time range, **so that** I can focus on one sub-area of my corpus.

**Acceptance criteria**:

- AC-1: Each filter dimension is independently toggleable.
- AC-2: Filters compose (AND across dimensions).
- AC-3: The current filter state is reflected in the URL so the view can be bookmarked and shared (within the same workspace).
- AC-4: No filter input requires the user to know or type a UUID. Documents are picked from a combobox by filename; entities are picked from a debounced typeahead by name; entity / edge types and tags are picked from chip groups whose options are loaded from the workspace's actual graph (with per-option counts).

Satisfies: FR-18. Sprint 5c shipped the picklist refactor (`DocumentPicker`, `EntityTypeahead`, `TypeMultiselect`, `TagPicker`).

### US-3.3 — Inspect a node's provenance (P0)

**As** Maya (P-1), **I want** to click any entity in the graph and see the atomic notes and documents it was extracted from, **so that** I can verify the LLM did not hallucinate.

**Acceptance criteria**:

- AC-1: A selection panel shows the entity's properties, all originating notes, and source documents with page references.
- AC-2: Clicking through to a note opens the note view; the graph keeps the selection.
- AC-3: Provenance is read-only; the user cannot accidentally edit source citations from this view.

Satisfies: FR-14, FR-19.

### US-3.4 — Rename or merge entities from the graph view (P0)

**As** Maya (P-1), **I want** to fix entity dedup mistakes (e.g., "A. Einstein" and "Albert Einstein") directly in the graph view, **so that** I do not have to context-switch to a separate admin screen.

**Acceptance criteria**:

- AC-1: Selecting two entities and choosing "Merge" combines them; all incident edges are rewritten.
- AC-2: Renaming an entity updates its display label everywhere; provenance is unchanged.
- AC-3: A merge can be reversed at any time via persisted **Full undo** (restores the victim entity, its provenance junctions, the survivor's pre-merge fields, and the audited incident relationships from `merge_audit_log`) or **Revert survivor fields**. Undo remains available indefinitely until the survivor row is deleted.

Satisfies: FR-15, FR-20. Sprint 5b shipped the persisted-undo affordance via `POST .../graph/entities/{id}/unmerge`.

### US-3.5 — Add or remove an edge from the graph view (P0)

**As** Dev (P-2), **I want** to add a missing relationship or remove an incorrect one directly in the graph view, **so that** my graph reflects my expert judgment.

**Acceptance criteria**:

- AC-1: Selecting two entities offers "Connect"; the user picks an edge type and optional temporal validity.
- AC-2: A manually-added edge is tagged as user-created in its provenance.
- AC-3: Removing an edge preserves its history (it is marked as ended, not destroyed, consistent with Graphiti's temporal model).

Satisfies: FR-13, FR-21.

### US-3.6 — Mark the graph as reviewed (create a snapshot) (P0)

**As** Maya (P-1), **I want** to mark my working graph as "reviewed" with a name and short description, **so that** I have a stable, named point to persist or roll back to.

**Acceptance criteria**:

- AC-1: Creating a snapshot freezes the current entities, edges, and notes in an immutable GraphSnapshot.
- AC-2: The snapshot is named, dated, and optionally annotated.
- AC-3: The working graph continues to be editable; snapshots are immutable.

Satisfies: FR-22.

### US-3.7 — Define a custom entity or edge type (P1)

**As** Ada the Admin (P-5), **I want** to define a custom entity type (e.g., "ClinicalTrial") and a custom edge type (e.g., "FUNDED_BY") for my workspace, **so that** extraction maps to our team's ontology.

**Acceptance criteria**:

- AC-1: Custom types are scoped per workspace.
- AC-2: New ingestion runs use the custom types in extraction prompts. The P0 canonical Pydantic taxonomy (`Person`, `Organization`, `Location`, `Document`, `Standard`, `Equipment`, `Process`, `Material`, `Event`, `Concept`, plus the 8 canonical edge types) remains available as the default; per-workspace custom types extend it rather than replacing it.
- AC-3: Existing entities and edges of standard types can be relabeled to custom types in bulk via a guided flow.

Satisfies: FR-16. The P0 canonical taxonomy shipped in Sprint 5c.

### US-3.8 — Review and approve a graph snapshot (P0)

**As** Maya (P-1), **I want** to record a review decision on a snapshot (approve, reject, or request changes), **so that** persistence to an external graph DB is gated on an explicit reviewed-and-approved state and the team has an audit trail of who signed off on what.

**Acceptance criteria**:

- AC-1: The Snapshot Detail page exposes three actions: `Approve`, `Reject`, and `Needs changes`. Each writes a `SnapshotReview` row keyed by `(snapshot_id, reviewer_user_id)` and overwrites any prior decision from the same reviewer.
- AC-2: Each decision accepts optional `rationale` text (≤ 2000 chars) shown alongside the decision badge.
- AC-3: The Snapshots list shows the current decision badge per snapshot (`none` / `approved` / `rejected` / `needs_changes`).
- AC-4: Persistence is gated on `approved`; `needs_changes` and `rejected` block persistence with a clear inline message and a link back to the review action.
- AC-5: Re-reviewing flips the badge atomically; the original review row is updated, not duplicated.

Satisfies: FR-22 (snapshot durability) and the review gate behind Epic 4 persistence. Sprint 5b shipped `POST .../snapshots/{id}/review` and the two-state UI; the three-state version follows TD-014.

## Epic 4 — External Persistence

### US-4.1 — Configure an external graph target (P0)

**As** Otto the Operator (P-3), **I want** to point my workspace at my existing Neo4j (or Postgres+AGE) instance, **so that** persistence lands in a database I already operate.

**Acceptance criteria**:

- AC-1: The user can add a target of type Neo4j or Postgres+AGE with a name, connection string, and credentials.
- AC-2: Credentials are encrypted at rest and never returned by any API.
- AC-3: A "Test connection" action verifies reachability and required permissions without writing data.

Satisfies: FR-23, FR-24, NFR-3.

### US-4.2 — Persist a snapshot to a target (P0)

**As** Maya (P-1), **I want** to push a named GraphSnapshot to my Neo4j instance, **so that** I can query the graph from my own tools.

**Acceptance criteria**:

- AC-1: The user picks a snapshot and a target and starts a PersistenceJob.
- AC-2: The job runs asynchronously; the UI shows progress and lets the user cancel.
- AC-3: On completion, the user sees the count of nodes/edges written and any warnings (e.g., constraint conflicts).
- AC-4: The job records who started it, which snapshot, which target, the start/end time, and the result.

Satisfies: FR-25, FR-26, NFR-7.

### US-4.3 — Non-destructive persistence by default (P0)

**As** Otto (P-3), **I want** persistence to be additive by default, **so that** zkast cannot accidentally wipe other data in my Neo4j.

**Acceptance criteria**:

- AC-1: The default mode is "upsert": create new nodes/edges, update changed ones, never delete.
- AC-2: A "replace" mode is available but requires explicit opt-in per job with a confirmation step that lists what will be deleted.
- AC-3: Persistence only touches nodes and edges that belong to zkast (identified by a workspace-scoped property/label).

Satisfies: FR-27.

### US-4.4 — Roll back to a previous snapshot (P1)

**As** Dev (P-2), **I want** to push a previous snapshot to my target DB, **so that** I can recover from a regression I introduced after a manual edit.

**Acceptance criteria**:

- AC-1: The user can pick any prior snapshot from the workspace and start a PersistenceJob with it.
- AC-2: A diff summary (added / removed / changed nodes and edges) is shown before the user confirms.

Satisfies: FR-25, FR-27.

## Epic 5 — Workspace and Settings

### US-5.1 — First-run setup in single-user mode (P0)

**As** Maya (P-1), **I want** zkast to work out of the box without an account, **so that** I can try it without setting up auth.

**Acceptance criteria**:

- AC-1: On first launch with auth bypass enabled, a default workspace is auto-created.
- AC-2: The user is prompted to enter a Cohere API key on first run and is told it is stored encrypted locally.
- AC-3: No data is sent to any third party other than the configured LLM provider.

Satisfies: FR-33, NFR-2, NFR-3.

### US-5.2 — Configure LLM models (P0; provider selection in P1)

**As** Dev (P-2), **I want** to choose which models the pipeline uses per workspace, **so that** I can balance cost and quality.

**Acceptance criteria**:

- AC-1: In P0 only one provider is supported (Cohere). The provider selector is visible but disabled with explanatory copy ("More providers coming in the next release.").
- AC-2: Within Cohere, the user can choose distinct models for "small" (extraction; default `command-r7b-12-2024`) and "large" (reasoning / note generation; default `command-a-plus-05-2026`) tasks, plus an embedding model (default `embed-v4.0`) and a rerank model (default `rerank-v4.0-fast`). Other Cohere embed/rerank IDs remain valid workspace overrides.
- AC-3: Changing models does not break in-flight jobs; they finish on the model they started with.
- AC-4: In P1, the provider selector becomes active and adds OpenAI, OpenAI-compatible generic, Ollama, Gemini, and Anthropic.

Satisfies: FR-29.

### US-5.3 — Rotate an API key (P1)

**As** Ada (P-5), **I want** to rotate the workspace's LLM API key without restarting the service, **so that** I can respond to a leaked key quickly.

**Acceptance criteria**:

- AC-1: Updating the key takes effect for all new pipeline calls within 60 seconds.
- AC-2: In-flight calls continue with the old key until they finish or fail; on retry they pick up the new key.
- AC-3: The old key is wiped from memory once no active jobs reference it.

Satisfies: FR-30, NFR-3.

### US-5.4 — Tune pipeline parameters (P1)

**As** Dev (P-2), **I want** to adjust chunk size, max notes per document, and language, **so that** I can tune the pipeline to my corpus.

**Acceptance criteria**:

- AC-1: Parameters are stored per workspace with sensible defaults.
- AC-2: Defaults are documented in the UI with the impact of changing them.

Satisfies: FR-31.

## Epic 6 — Multi-user and Access Control

### US-6.1 — Sign up and sign in (P1)

**As** any user in a self-hosted multi-user deployment, **I want** to create an account with email + password (or SSO in P2), **so that** I can have my own private workspaces.

**Acceptance criteria**:

- AC-1: Email/password auth is supported in P1; SSO (Google, GitHub) is supported in P2.
- AC-2: Sessions expire after a configurable idle period; the default is 30 days for self-hosted.
- AC-3: Password reset is supported via email.

Satisfies: FR-32, NFR-11.

### US-6.2 — Invite a member to a workspace (P1)

**As** Ada (P-5), **I want** to invite a teammate to my workspace with a specific role, **so that** they can contribute without me handing them my account.

**Acceptance criteria**:

- AC-1: The admin can invite a user by email with role Owner, Editor, or Viewer.
- AC-2: The invitee receives an invite link valid for a configurable period (default 7 days).
- AC-3: Viewers cannot edit notes, the graph, or settings.
- AC-4: Editors cannot manage members or rotate workspace credentials.

Satisfies: FR-34.

### US-6.3 — Remove or re-role a member (P1)

**As** Ada (P-5), **I want** to remove a member or change their role, **so that** I can respond to team changes.

**Acceptance criteria**:

- AC-1: A removed member loses access within 60 seconds.
- AC-2: Re-roling is logged in the audit log.
- AC-3: The last Owner cannot be removed; the workspace must always have at least one Owner.

Satisfies: FR-34.

### US-6.4 — View the audit log (P1)

**As** Ada (P-5), **I want** to see who did what and when on my workspace, **so that** I can investigate incidents.

**Acceptance criteria**:

- AC-1: The audit log captures: member changes, settings changes, API key rotations, persistence jobs, snapshot creation, target configuration changes.
- AC-2: Entries are immutable.
- AC-3: The log can be filtered by member, action type, and time range.

Satisfies: NFR-7.

## Epic 7 — Observability and Reliability

### US-7.1 — Diagnose a failed ingestion run (P0)

**As** Otto (P-3), **I want** to see why a document failed and retry just that document, **so that** I do not have to re-process my entire corpus.

**Acceptance criteria**:

- AC-1: A failed Document shows the failing stage, error class, and (in self-hosted) a link to the OpenTelemetry trace.
- AC-2: The user can retry from the last successful stage, not from the beginning.
- AC-3: Retries respect provider rate limits.

Satisfies: FR-4, NFR-6, NFR-7.

### US-7.2 — Cancel a long-running job (P0)

**As** Maya (P-1), **I want** to cancel a stuck ingestion or persistence job, **so that** I am not held hostage by a misbehaving provider.

**Acceptance criteria**:

- AC-1: Any IngestionRun or PersistenceJob has a "Cancel" action while it is running.
- AC-2: Cancellation is acknowledged within 10 seconds; partial state is preserved and clearly marked.
- AC-3: No external graph DB writes occur after cancellation is accepted.

Satisfies: NFR-6, C-4.

### US-7.3 — Opt out of telemetry (P0)

**As** Otto (P-3), **I want** telemetry off by default in self-hosted mode, **so that** my deployment makes no outbound calls except to the configured LLM provider (Cohere in P0).

**Acceptance criteria**:

- AC-1: Telemetry is disabled by default in self-hosted mode and the UI shows its status.
- AC-2: An environment variable and a settings toggle both work to disable it.
- AC-3: When disabled, no network calls of any kind go to telemetry endpoints.

Satisfies: NFR-2.

### US-7.4 — Watch a live ingestion in progress (P0)

**As** Dev (P-2), **I want** to open a collapsible bottom-edge log drawer that streams per-stage events while a PDF is ingesting, **so that** I can tell whether the pipeline is making progress, paused, or stuck without `docker compose exec`.

**Acceptance criteria**:

- AC-1: A persistent bottom-edge drawer (`Pipeline log`) is mounted on every workspace route. Collapsed by default; the strip shows the count of active jobs (or `idle`) and total line count. The collapsed/expanded state persists per browser via `localStorage`.
- AC-2: When a PDF is uploaded or a stage is retried, the drawer registers an active job and immediately renders `stage_started` / `stage_progress` / `log` / `metric` / `stage_completed` events from the SSE stream (`GET /jobs/{id}/events?workspaceId=...`).
- AC-3: The SSE endpoint replays the last ~200 events from the per-job Redis Stream on connect so opening the drawer mid-run shows recent history, not a blank "Waiting for events…" forever.
- AC-4: Filters are available for log level (`info` / `warning` / `error`) and per-job. A `Follow tail` checkbox sticks the view to the latest line; manual scroll pauses follow-tail. `Copy` ships the filtered log to the clipboard.
- AC-5: `metric` events whose name implies a graph mutation (`entity_count`, `edge_count`, `note_count`) cross-fire a graph invalidation event so the canvas refetches without polling.

Satisfies: FR-3 (visible pipeline progress) and a new product affordance for operator confidence. Sprint 5b shipped the `record_log` / `record_metric` plumbing, the Redis Stream replay, and the JobLogConsole drawer.

### US-7.5 — Diagnose pipeline state (P0)

**As** Otto (P-3), **I want** a Settings → Diagnostics page that summarizes queue depth, in-flight jobs, stalled documents, per-stage latency, and Redis hash hygiene, **so that** I can audit pipeline health and take corrective action without inspecting Redis or Postgres directly.

**Acceptance criteria**:

- AC-1: A `/settings/diagnostics` route is reachable by Owners and shows arq queue depth, in-progress job IDs, and per-stage job counts.
- AC-2: A "Stalled documents" panel lists any document in an active status whose `ingestion_runs.last_heartbeat_at` is older than `HEARTBEAT_STALE_THRESHOLD_S`, with deep links to the document detail. A worker-side cron flips these to `failed` within ~60 s; the panel exists so the user understands what just happened.
- AC-3: A "Per-stage latency" panel shows p50 and p95 for `parsing` / `generating_notes` / `extracting_graph` over the last 100 runs.
- AC-4: A "Hash hygiene" panel shows total `zkast:job:*` Redis hashes and a count of those in terminal status, with a `Cleanup stale hashes` action that confirms via the in-app `useConfirm` dialog and reports results via toast. The action never deletes hashes for live (`running` / `queued`) jobs.
- AC-5: The page polls every 5 seconds while open; no other component refreshes more aggressively.

Satisfies: NFR-3 (operator visibility) and a new product affordance. Sprint 5b shipped `GET /admin/diagnostics`, `POST /admin/cleanup-stale-job-hashes`, and the Diagnostics page.

## Epic 8 — Grounded Chat with the Knowledge Graph

### US-8.1 — Ask a grounded question (P0)

**As** Maya (P-1), **I want** to type a natural-language question and get an answer that is grounded in my own notes and documents, **so that** I can interrogate my corpus without re-reading every PDF.

**Acceptance criteria**:

- AC-1: A workspace exposes a Chat surface (panel and full-page) where the user can type a question and submit it.
- AC-2: Submitting a question triggers hybrid retrieval over the workspace's working graph (semantic + keyword + graph traversal) and selects a bounded set of atomic notes, entities, and relationships to ground the answer.
- AC-3: The answer is generated by Cohere Chat with Cohere's document-grounding mode enabled.
- AC-4: When retrieval returns no useful context, the assistant explicitly refuses to answer from parametric knowledge and tells the user it cannot ground a response.
- AC-5: The answer streams token-by-token; the user can stop generation at any time.
- AC-6: Typed-aggregation questions ("how many X are in this document", "list all Y", "count Z by type") return the count and named exemplars from the workspace graph's structured taxonomy, not a vector-extracted approximation. Sprint 6 ships this as a synthesized graph-context grounding document; Sprint 6b's eval pins the contract and Sprint 7's TD-015 handlers replace the document with true graph traversal. (Failure mode pinned by BUG-013.)

Satisfies: FR-35, FR-36, FR-37, FR-39, FR-45.

### US-8.2 — See and follow citations (P0)

**As** Maya (P-1), **I want** every claim in the answer to be cited, with each citation linking back to the source note or document page, **so that** I can verify before trusting.

**Acceptance criteria**:

- AC-1: Each cited span in the answer is visually marked (e.g., a numbered superscript or chip) and reveals the cited source(s) on hover.
- AC-2: Clicking a citation navigates to the originating atomic note in the Notes panel; if the cited material includes a document chunk, the document preview scrolls to the relevant page range.
- AC-3: Citations distinguish between note-grounded and entity/edge-grounded sources visually (e.g., different icons).
- AC-4: A citation count and a coverage indicator (percentage of the answer that is cited vs ungrounded) are visible in the message footer.

Satisfies: FR-37, FR-38.

### US-8.3 — Scope a chat session (P0)

**As** Dev (P-2), **I want** to scope a chat session to specific documents, tags, entity types, or a snapshot, **so that** I can ask precise questions without retrieving across the entire corpus.

**Acceptance criteria**:

- AC-1: A "Scope" control on the chat session lets the user pick: one or more documents, one or more tags, one or more entity/edge types, a time range, or a specific GraphSnapshot.
- AC-2: The active scope is visible in the session header and on every assistant message produced under that scope.
- AC-3: Changing the scope mid-session is recorded as a new turn boundary; previous messages retain the scope they were produced under.
- AC-4: A session pinned to a GraphSnapshot produces reproducible answers — re-running the same question must return retrieval results consistent with that snapshot.

Satisfies: FR-40.

### US-8.4 — Inspect retrieval for any answer (P0)

**As** any user, **I want** to see exactly what notes, entities, and edges were retrieved for an answer, **so that** I can diagnose bad responses and trust good ones.

**Acceptance criteria**:

- AC-1: Each assistant message has a "Show retrieved context" affordance.
- AC-2: Opening it lists the retrieved items with their relevance scores and lets the user open each in its native view (note, entity, edge).
- AC-3: The retrieval record is persisted with the message; opening it later shows the same items even if the working graph has since changed.

Satisfies: FR-41.

### US-8.5 — Manage chat sessions (P0)

**As** any user, **I want** to list, rename, resume, and delete chat sessions in my workspace, **so that** I can organize my conversations as my workspace grows.

**Acceptance criteria**:

- AC-1: A Chat home page lists sessions sorted by recent activity, with title, last-message preview, scope summary, and last-modified timestamp.
- AC-2: The user can rename and delete sessions.
- AC-3: Sessions auto-generate a default title from the first question, which the user can override.
- AC-4: Resuming a session loads its full message history; messages render exactly as they were stored, including citations and retrieval records.

Satisfies: FR-42.

### US-8.6 — Regenerate the last answer (P0)

**As** Maya (P-1), **I want** to regenerate the last assistant message, **so that** I can get a fresh answer when the first one was unhelpful.

**Acceptance criteria**:

- AC-1: A "Regenerate" action appears on the last assistant message in a session.
- AC-2: Regeneration re-runs retrieval and generation; the previous answer is preserved as a sibling alternate (collapsible).
- AC-3: The user can flip between alternates and pick one to be "the answer" for that turn.

Satisfies: FR-43.

### US-8.7 — Ask about a specific entity or note (P0)

**As** Maya (P-1), **I want** to start a chat scoped to the entity, note, or subgraph I'm currently looking at, **so that** I don't have to retype context.

**Acceptance criteria**:

- AC-1: The graph view, the entity detail, and the note detail each expose an "Ask about this" action.
- AC-2: The action opens (or focuses) a chat session pre-scoped to the selected item (and, for an entity, its N-hop neighborhood; N is a per-workspace setting, default 1).
- AC-3: The default first prompt is pre-filled with the selection's name or title, and the user can edit it before submitting.

Satisfies: FR-44.

### US-8.8 — Cancel a streaming answer (P0)

**As** any user, **I want** to cancel an answer mid-stream, **so that** I can stop the model when I see it going in the wrong direction.

**Acceptance criteria**:

- AC-1: A visible Stop control replaces the Send control while a response is streaming.
- AC-2: Pressing Stop ends the stream within one second and marks the message as `cancelled`; any tokens already streamed are preserved.
- AC-3: Cancellation does not invalidate the retrieval record; the user can still inspect what was retrieved.

Satisfies: FR-39, NFR-6.

### US-8.9 — Refuse ungrounded answers gracefully (P0)

**As** Otto (P-3), **I want** the assistant to refuse to answer questions that cannot be grounded in my workspace, **so that** I never end up with model hallucinations dressed up as my own notes.

**Acceptance criteria**:

- AC-1: When retrieval returns insufficient context, the answer is a short refusal that explicitly says the workspace does not contain enough information to answer. "Insufficient context" means **no grounding documents at all** — neither hybrid-search fact snippets nor the synthesized graph-context document. A workspace that contains *any* typed entities still has the graph-context document available, so the LLM can answer at least "the workspace is empty" / "I have only Locations and Organizations" rather than refusing outright.
- AC-2: The refusal carries a "Suggested next step" affordance (e.g., upload relevant documents, broaden scope, lower the relevance threshold).
- AC-3: Refusals do not count against the citation coverage metric (i.e., a refusal with zero citations is not flagged as ungrounded).

Satisfies: FR-45.

### US-8.10 — Export a chat transcript (P1)

**As** Dev (P-2), **I want** to export a chat session to Markdown with citations preserved, **so that** I can paste reasoning chains into my notes or dissertation drafts.

**Acceptance criteria**:

- AC-1: An "Export" action produces a Markdown file with one section per turn.
- AC-2: Citations are rendered as numbered footnotes, each linking to an in-app URL for the source note and an external page-anchored URL for the source PDF if available.
- AC-3: The export includes session metadata (workspace, scope, timestamp, model versions, snapshot id if pinned).

Satisfies: FR-42.

### US-8.11 — Share a chat session read-only inside the workspace (P1)

**As** Ada (P-5), **I want** to share a chat session read-only with my workspace teammates, **so that** I can publish a curated Q&A view of our knowledge.

**Acceptance criteria**:

- AC-1: An Owner or Editor can mark a session as shared with the workspace. Viewers see it read-only; Editors and Owners see it as editable.
- AC-2: Shared sessions appear in the workspace's Chat home page for all members under a "Shared" filter.
- AC-3: Edits or deletions to a shared session are recorded in the audit log.

Satisfies: FR-42.

## Epic 9 — SaaS-Specific (P2)

### US-9.1 — Sign up via SSO (P2)

**As** Priya (P-4), **I want** to sign up with my Google account, **so that** I do not have to manage another password.

**Acceptance criteria**:

- AC-1: Google and GitHub SSO are supported.
- AC-2: SSO accounts can be linked to an existing email-password account.

### US-9.2 — Share a read-only graph view (P2)

**As** Priya (P-4), **I want** to share a read-only link to a snapshot with a teammate, **so that** they can explore the graph without an account.

**Acceptance criteria**:

- AC-1: Sharing creates a signed, expiring link scoped to one snapshot.
- AC-2: Access can be revoked at any time.
- AC-3: Anonymous viewers cannot edit, persist, or download underlying PDFs.

### US-9.3 — Per-tenant rate limits and quotas (P2)

**As** the SaaS operator, **I want** quotas on uploads, LLM calls, and persistence jobs per tenant, **so that** one user cannot degrade the service for others.

**Acceptance criteria**:

- AC-1: Quotas are configurable per pricing tier.
- AC-2: Approaching a quota produces a UI warning; hitting one produces a clear error and a billing-aware upgrade prompt.

## Story Map Summary

| Phase | Epics covered (key stories)                                                                     |
| ----- | ----------------------------------------------------------------------------------------------- |
| P0    | 1 (all), 2 (1–6), 3 (1–6), 4 (1–3), 5 (1–2), 7 (1–3), 8 (1–9)                                    |
| P1    | 2.* (refinements), 3.7, 4.4, 5.3–5.4, 6 (all), 7.* (refined), 8.10–8.11                          |
| P2    | 9 (all), all prior epics in multi-tenant form                                                   |

## Related Specifications

- [prd.md](prd.md) — Source requirements for these stories.
- [personas.md](personas.md) — Personas referenced in the "As a" clauses.
- [apis.md](apis.md) — API surface that implements these stories.
- [uiux.md](uiux.md) — UI flows for the user-facing stories.
