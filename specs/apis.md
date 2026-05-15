# zkast — API Specification

This document defines the **external HTTP API** exposed by zkast's web tier. It is a behavior contract: each endpoint lists purpose, inputs, outputs, authorization, and error cases. No code, no schemas-as-JSON. Implementation is owned by [techstack.md](techstack.md); the data those endpoints move is defined in [datamodel.md](datamodel.md).

## Conventions

### Base URL

- Self-hosted: `http://<host>:<port>/api/v1`
- SaaS: `https://api.zkast.app/v1`

### Versioning

- The API is versioned in the URL (`/v1`).
- Additive changes do not bump the version. Breaking changes ship a new version and run in parallel for one minor release.

### Authentication

- **Single-user bypass (P0)**: All endpoints accept anonymous calls. The synthetic local user is implied.
- **Multi-user (P1+)**: All endpoints require a session cookie (browser) or bearer token (programmatic).
- **Service-to-service** (web -> pipeline): an internal `X-Zkast-Internal-Token` shared secret; not exposed publicly.

### Authorization Model

- Most endpoints are scoped to a workspace by a path segment (`/workspaces/{workspaceId}/...`).
- The caller must be a Member of that workspace.
- Mutating endpoints require role `editor` or `owner`; admin endpoints (members, API keys, settings) require `owner`.

### Identifiers

- All resource ids are UUIDv4 strings.
- Slugs are accepted as aliases for workspace ids in some endpoints (`/workspaces/{slugOrId}`).

### Content Types

- Request and response bodies are JSON unless otherwise noted.
- File uploads use `multipart/form-data`.
- Streaming endpoints use `text/event-stream` (SSE).

### Pagination

- List endpoints accept `limit` (default 25, max 200) and `cursor` (opaque). Responses include `next_cursor` (nullable).

### Errors

All errors return a structured body:

- `error.code` (machine-readable string).
- `error.message` (human-readable).
- `error.details` (optional, action-specific).
- `error.trace_id` (when available).

**Standard error codes**:

| HTTP | Code                            | Meaning                                                          |
| ---- | ------------------------------- | ---------------------------------------------------------------- |
| 400  | `validation_failed`             | Input failed validation. `details` lists fields.                 |
| 401  | `unauthenticated`               | No / invalid session.                                            |
| 403  | `forbidden`                     | Authenticated but lacks role for the action.                     |
| 404  | `not_found`                     | Resource does not exist or caller cannot see it.                 |
| 409  | `conflict`                      | State conflict (e.g., name already used, snapshot immutable).    |
| 409  | `business_rule_violation`       | Semantic rule or resource busy (e.g., document delete/retry while ingestion is active — pipeline internal + web proxy). |
| 413  | `payload_too_large`             | Upload exceeds configured limit.                                 |
| 415  | `unsupported_media_type`        | File rejected by content type.                                   |
| 422  | `business_rule_violation`       | Semantic rule failed (e.g., would remove last Owner).            |
| 429  | `rate_limited`                  | Workspace or tenant rate limit hit.                              |
| 499  | `client_cancelled`              | Client-cancelled long-running operation.                         |
| 500  | `internal_error`                | Unhandled error. Trace id is always present.                     |
| 502  | `provider_error`                | Upstream LLM or graph DB returned an error.                      |
| 504  | `provider_timeout`              | Upstream call timed out.                                         |

### Long-Running Operations

Operations that exceed 60 seconds (ingestion, persistence, bulk operations) are modeled as **jobs**:

1. The request returns `202 Accepted` with a `job_id` and a `status_url`.
2. The client polls `GET /jobs/{job_id}` or subscribes to `GET /jobs/{job_id}/events` (SSE).
3. Job state machine: `queued -> running -> (succeeded | partial | failed | cancelled)`.
4. Jobs are cancellable via `POST /jobs/{job_id}/cancel`.

### Idempotency

- Mutating endpoints accept an `Idempotency-Key` header. Replaying the same key within 24 hours returns the original response.

### Webhooks (P2)

- Workspaces can register webhook endpoints to receive events (`job.completed`, `snapshot.created`, `persistence.completed`).
- Webhook deliveries are signed with HMAC-SHA256 using a per-workspace secret.

---

## Resources

### Auth & Session

#### `POST /auth/sign-in` (P1+)

**Purpose**: Begin an authenticated session.

**Inputs**: `email`, `password` (or OAuth flow parameters).

**Outputs**: Session cookie (browser) or token (programmatic), the authenticated user record.

**Auth**: None.

**Errors**: `validation_failed`, `unauthenticated` (bad credentials), `rate_limited`.

#### `POST /auth/sign-out`

**Purpose**: End the current session.

**Outputs**: 204 No Content.

**Auth**: Any authenticated user.

#### `GET /auth/session`

**Purpose**: Return the currently authenticated user and their memberships.

**Outputs**: `user`, `memberships[]`.

**Auth**: Required.

#### `POST /auth/password/reset-request` (P1+)

**Purpose**: Email a password reset link.

**Inputs**: `email`.

**Outputs**: 202 Accepted (always — does not reveal whether the email exists).

#### `POST /auth/password/reset`

**Purpose**: Complete a password reset.

**Inputs**: `token`, `new_password`.

**Outputs**: 204.

**Errors**: `validation_failed`, `unauthenticated` (bad/expired token).

---

### Workspaces

#### `GET /workspaces`

**Purpose**: List workspaces the caller can access.

**Outputs**: Paginated list of workspaces with the caller's role in each.

**Auth**: Required.

#### `POST /workspaces` (P1+)

**Purpose**: Create a new workspace. The creator becomes an Owner.

**Inputs**: `name`, optional `slug`, optional `description`.

**Outputs**: The created workspace, with the caller's Owner membership.

**Errors**: `validation_failed`, `conflict` (slug taken).

#### `GET /workspaces/{workspaceId}`

**Purpose**: Get a workspace's settings and stats.

**Outputs**: The workspace, including pipeline settings and counts (documents, notes, entities, edges, snapshots).

**Auth**: Member.

#### `PATCH /workspaces/{workspaceId}`

**Purpose**: Update workspace name, description, or pipeline settings.

**Inputs**: Any subset of the above.

**Outputs**: Updated workspace.

**Auth**: Owner.

**Errors**: `validation_failed`, `business_rule_violation` (e.g., chunk size out of range).

#### `DELETE /workspaces/{workspaceId}` (P1+)

**Purpose**: Permanently delete a workspace and all its data.

**Inputs**: Body must include the workspace `slug` as a confirmation token.

**Outputs**: 204 (or 202 with a job for very large workspaces).

**Auth**: Owner.

**Errors**: `validation_failed` (wrong confirmation), `business_rule_violation` (active persistence job).

---

### Memberships (P1+)

#### `GET /workspaces/{workspaceId}/members`

**Purpose**: List members and roles.

**Outputs**: Paginated members.

**Auth**: Member.

#### `POST /workspaces/{workspaceId}/members`

**Purpose**: Invite a member by email.

**Inputs**: `email`, `role` (`owner | editor | viewer`).

**Outputs**: Invitation record with expiry.

**Auth**: Owner.

**Errors**: `conflict` (already a member), `validation_failed`.

#### `PATCH /workspaces/{workspaceId}/members/{userId}`

**Purpose**: Change a member's role.

**Inputs**: `role`.

**Outputs**: Updated membership.

**Auth**: Owner.

**Errors**: `business_rule_violation` (would remove last Owner).

#### `DELETE /workspaces/{workspaceId}/members/{userId}`

**Purpose**: Remove a member.

**Outputs**: 204.

**Auth**: Owner.

**Errors**: `business_rule_violation` (would remove last Owner).

---

### Documents

#### `GET /workspaces/{workspaceId}/documents`

**Purpose**: List documents.

**Query**: `status`, `q` (substring of filename), `sort` (`created_at | updated_at | name`), pagination.

**Outputs**: Paginated documents with current status and last IngestionRun summary.

**Auth**: Member.

#### `POST /workspaces/{workspaceId}/documents`

**Purpose**: Upload one or more PDFs.

**Inputs** (`multipart/form-data`):

- One or more `file` parts.
- Optional `replaces_document_id` (only meaningful for a single file).
- Optional `auto_start` (boolean, default true): start ingestion immediately.

**Outputs**: 202 Accepted with `documents[]` (id, status `queued`) and per-document `job_id` for the initial IngestionRun.

**Auth**: Editor.

**Errors**: `payload_too_large`, `unsupported_media_type`, `validation_failed`, `rate_limited`.

#### `GET /workspaces/{workspaceId}/documents/{documentId}`

**Purpose**: Get a single document's metadata, status, and history of IngestionRuns.

**Outputs**: Document + `ingestion_runs[]`.

**Auth**: Member.

#### `DELETE /workspaces/{workspaceId}/documents/{documentId}`

**Purpose**: Delete a document.

**Inputs**: `cascade` (enum: `document_only`, `exclusive_derivatives`). Default `document_only`.

**Outputs**:

- `document_only`: 204.
- `exclusive_derivatives`: 202 with a job describing the cascade work.

**Auth**: Editor.

**Errors**: `business_rule_violation` (active IngestionRun on this document).

#### `GET /workspaces/{workspaceId}/documents/{documentId}/preview`

**Purpose**: Stream a low-resolution preview image or first-page extract.

**Outputs**: `image/png` or JSON with extracted text snippet.

**Auth**: Member.

#### `GET /workspaces/{workspaceId}/documents/{documentId}/file`

**Purpose**: Download the original PDF.

**Outputs**: `application/pdf` stream.

**Auth**: Member.

---

### Ingestion Runs

#### `GET /workspaces/{workspaceId}/documents/{documentId}/ingestion-runs`

**Purpose**: List IngestionRuns for a document.

**Outputs**: Paginated runs with status, stage timings, and stats.

**Auth**: Member.

#### `POST /workspaces/{workspaceId}/documents/{documentId}/ingestion-runs`

**Purpose**: Start a new IngestionRun (retry, or re-run on changed settings).

**Inputs**: Optional `from_stage` (resume from a stage; default `parsing`).

**Outputs**: 202 with a `job_id`.

**Auth**: Editor.

**Errors**: `business_rule_violation` (run already active for this document).

#### `GET /workspaces/{workspaceId}/ingestion-runs/{runId}/episodes`

**Purpose**: List Episodes produced by a run.

**Query**: `q` (text search), pagination.

**Outputs**: Paginated Episodes.

**Auth**: Member.

---

### Atomic Notes

#### `GET /workspaces/{workspaceId}/notes`

**Purpose**: List atomic notes.

**Query**: `q` (full-text), `tags[]`, `document_id`, `agent_id` (North agent UUID — returns only notes whose `agent_id` matches), `origin`, `is_user_edited`, `sort`, pagination.

**Outputs**: Paginated notes with summary fields (title, tags, updated_at, document_id, agent_id when present).

**Auth**: Member.

#### `POST /workspaces/{workspaceId}/notes`

**Purpose**: Create a manual atomic note.

**Inputs**: `title`, `body`, `tags[]`.

**Outputs**: Created note.

**Auth**: Editor.

#### `GET /workspaces/{workspaceId}/notes/{noteId}`

**Purpose**: Get a note, including links and source episodes.

**Outputs**: Note, `links_out[]`, `links_in[]`, `source_episodes[]`.

**Auth**: Member.

#### `PATCH /workspaces/{workspaceId}/notes/{noteId}`

**Purpose**: Update fields of a note.

**Inputs**: Any subset of `title`, `body`, `tags[]`.

**Outputs**: Updated note.

**Auth**: Editor.

#### `DELETE /workspaces/{workspaceId}/notes/{noteId}`

**Purpose**: Delete a note.

**Outputs**: 204.

**Auth**: Editor.

#### `POST /workspaces/{workspaceId}/notes/{noteId}/merge`

**Purpose**: Merge two notes; the path note is the survivor.

**Inputs**: `other_note_id`, `field_selection` (per-field winner).

**Outputs**: Merged note with combined provenance.

**Auth**: Editor.

> **Sprint 5b**: writes a `merge_audit_log` row capturing the victim's
> payload + survivor pre-merge fields + episode provenance so
> `POST /notes/{noteId}/unmerge` can restore everything.

#### `POST /workspaces/{workspaceId}/notes/{noteId}/unmerge`

> **Sprint 5b — implemented**.

**Purpose**: Restore the most recently merged victim note from the audit log.

**Inputs**: empty body.

**Outputs**: `{ note: <restored victim> }`.

**Errors**: `not_found` when no audit row exists.

**Auth**: Editor.

#### `POST /workspaces/{workspaceId}/notes/{noteId}/split`

**Purpose**: Split a note into two atomic notes.

**Inputs**: `passage` (character range or selected text), `new_title`.

**Outputs**: The (updated) original note and the new note.

**Auth**: Editor.

#### `POST /workspaces/{workspaceId}/notes/{noteId}/links`

**Purpose**: Create a link from this note to another.

**Inputs**: `target_note_id`, `kind`, optional `custom_label`.

**Outputs**: NoteLink record.

**Auth**: Editor.

**Errors**: `validation_failed` (self-link), `conflict` (duplicate link).

#### `DELETE /workspaces/{workspaceId}/notes/{noteId}/links/{linkId}`

**Purpose**: Remove a link.

**Outputs**: 204.

**Auth**: Editor.

#### `GET /workspaces/{workspaceId}/notes/tags`

> **Sprint 5c — implemented**. Drives the tag-picker combobox in the graph filter bar.

**Outputs**: `{ tags: [{ name, count }] }` — distinct lowercase tag values present in `atomic_notes.tags` for the workspace, sorted by descending count.

**Auth**: Member.

---

### Knowledge Graph

> **Sprint 5 — implemented** (web `GET/POST/PATCH/DELETE …/graph*`, `…/snapshots*`, pipeline `internal/v1/workspaces/{workspace_id}/graph*`, `…/snapshots*`). Layout in the UI uses **Sigma.js + graphology** with **ForceAtlas2 in a Web Worker** (`graphology-layout-forceatlas2/worker`) when motion is allowed; `prefers-reduced-motion` uses a static circular layout. Filters are mirrored in the URL query string (`graph-filter-bar`). `GET …/graph/entities/{entityId}` returns **`incident_relationships`** (edges touching the entity) for the selection panel.

#### `GET /workspaces/{workspaceId}/graph`

**Purpose**: Return the current working graph in a form suitable for the visualization layer.

**Query**:

- `view` (`overview` | `subgraph`): controls level of detail.
- For `subgraph`: `seed_entity_ids[]`, `depth` (default 2).
- Filters: `entity_types[]`, `edge_types[]`, `document_id`, `tag`, `valid_at` (timestamp).
- `node_limit` (default 5000, max 25000).

**Outputs**: `nodes[]` (id, type, name, summary, properties, aliases, is_user_edited), `edges[]` (id, source, target, type, fact, valid_from, valid_to, confidence, origin, is_user_edited), `truncated` (boolean).

**Example** (shape only):

```json
{
  "nodes": [
    {
      "id": "b2c3d4e5-f6a7-4890-b1c2-d3e4f5a67890",
      "type": "Person",
      "name": "Ada Lovelace",
      "summary": "",
      "properties": {},
      "aliases": [],
      "is_user_edited": false
    }
  ],
  "edges": [
    {
      "id": "a1b2c3d-e4f5-6789-a012-b3c4d5e6f708",
      "source": "b2c3d4e5-f6a7-4890-b1c2-d3e4f5a67890",
      "target": "c3d4e5f6-a7b8-4901-c2d3-e4f5a6b78901",
      "type": "RELATED_TO",
      "fact": "",
      "valid_from": null,
      "valid_to": null,
      "confidence": 1.0,
      "origin": "generated",
      "is_user_edited": false
    }
  ],
  "truncated": false
}
```

#### `GET /workspaces/{workspaceId}/graph/entities`

**Purpose**: List entities with filtering, used by the entities table view.

**Query**: `q`, `type`, `tag`, `document_id`, pagination, `sort`.

**Outputs**: Paginated entities.

**Auth**: Member.

#### `GET /workspaces/{workspaceId}/graph/entities/{entityId}`

**Purpose**: Get a single entity with full detail and provenance.

**Outputs**: Entity, neighbors summary, source notes, source episodes, **`incident_relationships[]`** (same edge shape as `/graph`).

**Auth**: Member.

#### `PATCH /workspaces/{workspaceId}/graph/entities/{entityId}`

**Purpose**: Rename, retype, or edit properties of an entity.

**Inputs**: Any subset of `canonical_name`, `type`, `aliases[]`, `summary`, `properties`.

**Outputs**: Updated entity.

**Auth**: Editor.

**Errors**: `conflict` (would collide with another entity's `(type, canonical_name)`).

#### `POST /workspaces/{workspaceId}/graph/entities/{entityId}/merge`

**Purpose**: Merge two entities; the path entity survives.

**Inputs**: `other_entity_id`, `field_selection`.

**Outputs**: Merged entity; all incident edges are rewritten.

**Auth**: Editor.

#### `DELETE /workspaces/{workspaceId}/graph/entities/{entityId}`

**Purpose**: Delete an entity. Incident edges become orphaned and are surfaced in the UI for cleanup.

**Outputs**: 204.

**Auth**: Editor.

#### `GET /workspaces/{workspaceId}/graph/relationships/{relationshipId}`

**Purpose**: Get a single relationship with full detail and provenance.

**Outputs**: Relationship with source/target entity refs, source notes, episodes.

**Auth**: Member.

#### `POST /workspaces/{workspaceId}/graph/relationships`

**Purpose**: Create a relationship manually.

**Inputs**: `source_entity_id`, `target_entity_id`, `type`, optional `fact`, `valid_from`, `valid_to`.

**Outputs**: The created relationship (`origin: manual`, `is_user_edited: true`).

**Auth**: Editor.

**Errors**: `validation_failed` (e.g., type constraint violated).

#### `PATCH /workspaces/{workspaceId}/graph/relationships/{relationshipId}`

**Purpose**: Update a relationship's fields, including ending it by setting `valid_to`.

**Inputs**: Any subset of `type`, `fact`, `valid_from`, `valid_to`.

**Outputs**: Updated relationship.

**Auth**: Editor.

#### `DELETE /workspaces/{workspaceId}/graph/relationships/{relationshipId}`

**Purpose**: Mark a relationship as ended (sets `valid_to = now()`). Hard-delete is not exposed unless the parent entity is being deleted.

**Outputs**: 204.

**Auth**: Editor.

#### `GET /workspaces/{workspaceId}/graph/search`

> **Sprint 5b — implemented**. Calls Graphiti `search()` (hybrid: text + vector + rerank) scoped to the workspace `group_id`.

**Purpose**: Hybrid search over the working graph (semantic + keyword + graph traversal — Graphiti-backed).

**Query**: `q` (1–500 chars, required), `limit` (1–100, default 20).

**Outputs**: `results[]` (edges with `source_entity_id`, `target_entity_id`, `type`, `fact`, `uuid`), `query`, `limit`.

**Auth**: Member.

#### `POST /workspaces/{workspaceId}/graph/entities/{entityId}/unmerge`

> **Sprint 5b — implemented**. Restores the most recently merged victim entity from `merge_audit_log`. Re-creates the deleted row, restores its provenance junctions, rolls back the survivor's fields to their pre-merge values, and rewires audited incident relationships.

**Inputs**: empty body.

**Outputs**: `{ entity: <restored victim> }`.

**Errors**: `not_found` when no audit row exists for this survivor (no recent merge to undo, or already undone).

**Auth**: Editor.

#### `POST /workspaces/{workspaceId}/graph/cleanup-orphans`

> **Sprint 5b — implemented**. Runs the orphan-cleanup sweep manually. Normally fires automatically at the end of a document delete that selects `cascade=exclusive_derivatives`; this endpoint exposes the same sweep for ad-hoc operator use from the graph filter bar.

**Inputs**: empty body.

**Outputs**: `{ removed_entities, removed_relationships }` (integers).

**Auth**: Editor.

**Notes**: Preserves rows with `is_user_edited = true` and Relationships with `origin = manual` so user-curated graph state is never swept by this call.

#### `GET /workspaces/{workspaceId}/graph/entities/{entityId}/evidence`

> **Sprint 5c — implemented**. Paged read of the `entity_evidence` rows linked to an entity. Backs the "Evidence" tab in the entity detail panel and the "View in document" navigation.

**Query**: `limit` (1–200, default 50), `offset` (≥ 0, default 0).

**Outputs**: `{ items: [{ id, document_id, document_filename, episode_id, page, char_start, char_end, quote, method, attributes, created_at }], total }`.

**Auth**: Member.

#### `GET /workspaces/{workspaceId}/graph/types`

> **Sprint 5c — implemented**. Drives the entity- and edge-type multi-select pickers in the graph filter bar.

**Outputs**: `{ entity_types: [{ name, count }], edge_types: [{ name, count }] }` — distinct types currently present in the workspace's graph, sorted by descending count.

**Auth**: Member.

#### `GET /workspaces/{workspaceId}/graph/entities/search-typeahead`

> **Sprint 5c — implemented**. Cheap ILIKE-backed name search distinct from the heavier hybrid `/graph/search`; designed for keystroke-rate use by the seed-entity picker.

**Query**: `q` (1–200 chars, required), `limit` (1–50, default 20).

**Outputs**: `{ items: [{ id, name, type, degree }] }` — top matches sorted by descending degree.

**Auth**: Member.

---

### Custom Types (P1+)

#### `GET /workspaces/{workspaceId}/custom-types`

**Purpose**: List custom entity and edge types.

**Auth**: Member.

#### `POST /workspaces/{workspaceId}/custom-types`

**Purpose**: Define a new custom type.

**Inputs**: `kind` (`entity_type | edge_type`), `key`, `display_label`, `description`, optional `schema`, for `edge_type` optional endpoint constraints.

**Outputs**: The created CustomType.

**Auth**: Owner.

**Errors**: `conflict` (key taken).

#### `PATCH /workspaces/{workspaceId}/custom-types/{typeId}`

**Purpose**: Update display label, description, or schema additions (non-breaking only).

**Outputs**: Updated CustomType.

**Auth**: Owner.

#### `DELETE /workspaces/{workspaceId}/custom-types/{typeId}`

**Purpose**: Remove a custom type.

**Outputs**: 204.

**Auth**: Owner.

**Errors**: `business_rule_violation` (type still in use; caller must reassign first).

---

### Chat Sessions and Messages

Grounded chat with the workspace's knowledge graph. Streaming responses are delivered via SSE. Messages are append-only with the exception of regeneration (which adds an alternate to the last assistant turn).

#### Citation payload shape

Every assistant message returned by the API includes a `citations[]` array. Each citation has:

- `id` (UUID).
- `text_start`, `text_end` (integers): Character offsets into the message `content` for the cited span.
- `sources[]`: Each source has `kind` (`note | entity | relationship | episode | document_page`), an optional `id` (when `kind != document_page`), an optional `document_id`, optional `page_start`/`page_end`, and a short `excerpt`.

#### `GET /workspaces/{workspaceId}/chat-sessions`

**Purpose**: List chat sessions in a workspace.

**Query**: `q` (matches title), `created_by_user_id`, `pinned_snapshot_id`, `share_visibility`, sort (`last_activity_at | created_at | title`), pagination.

**Outputs**: Paginated sessions with title, scope summary, message count, last-message preview, and last-activity timestamp.

**Auth**: Member. Viewers see sessions that are either their own or shared `workspace_read`/`workspace_edit`.

#### `POST /workspaces/{workspaceId}/chat-sessions`

**Purpose**: Create a new chat session.

**Inputs**: Optional `title`, optional `scope` (documents, tags, entity_types, edge_types, valid_at, pinned_snapshot_id), optional `model_settings` (overrides workspace defaults), optional `seed_message` (a first user message to immediately submit).

**Outputs**: The created session; if `seed_message` was provided, the created `ChatMessage` (user turn) and a `job_id` for the assistant turn it triggers.

**Auth**: Editor.

**Errors**: `validation_failed`, `business_rule_violation` (snapshot from another workspace), `rate_limited`.

#### `GET /workspaces/{workspaceId}/chat-sessions/{sessionId}`

**Purpose**: Get a session's metadata.

**Outputs**: Session record including scope, model settings, share visibility, stats.

**Auth**: Member (subject to share visibility).

#### `PATCH /workspaces/{workspaceId}/chat-sessions/{sessionId}`

**Purpose**: Update a session's title, scope, model settings, or share visibility.

**Inputs**: Any subset.

**Outputs**: Updated session.

**Auth**: Editor; only the session's creator or an Owner can change `share_visibility`.

**Errors**: `business_rule_violation` (changing scope mid-session is recorded; previous messages keep their effective scope).

#### `DELETE /workspaces/{workspaceId}/chat-sessions/{sessionId}`

**Purpose**: Delete a session and all its messages, citations, and retrieval records.

**Outputs**: 204.

**Auth**: The session's creator or an Owner.

**Errors**: `business_rule_violation` (assistant turn currently streaming).

#### `GET /workspaces/{workspaceId}/chat-sessions/{sessionId}/messages`

**Purpose**: List messages in a session.

**Query**: `include_alternates` (boolean, default `false`), pagination (cursor-based ordered by `sequence`).

**Outputs**: Paginated messages. Each message includes role, content, status, citations (assistant only), `model_used`, and `effective_scope_snapshot`.

**Auth**: Member (subject to share visibility).

#### `POST /workspaces/{workspaceId}/chat-sessions/{sessionId}/messages`

**Purpose**: Submit a new user message. The server immediately persists the user turn and enqueues the assistant turn.

**Inputs**: `content` (string, required), optional `scope_overrides` for this turn only.

**Outputs**: 202 with the created user message, the assistant message id (status `pending`), and a `stream_url` for SSE.

**Auth**: Editor (or the session's creator if the session is private).

**Errors**: `validation_failed`, `business_rule_violation` (a streaming assistant turn already in progress in this session), `rate_limited`.

#### `GET /workspaces/{workspaceId}/chat-sessions/{sessionId}/messages/{messageId}`

**Purpose**: Get a single message with full detail including citations.

**Outputs**: Message.

**Auth**: Member (subject to share visibility).

#### `GET /workspaces/{workspaceId}/chat-sessions/{sessionId}/messages/{messageId}/stream`

**Purpose**: Subscribe to the SSE stream for an in-progress assistant message.

**Outputs**: `text/event-stream`. Event types:

- `retrieval_started` (no body).
- `retrieval_complete` — body includes the retrieval record id and an item count.
- `token` — body includes a text delta.
- `citation` — body includes a partial `ChatCitation` (may be emitted before the cited span is fully streamed; client buffers until span is complete).
- `message_complete` — body includes the final message id and citation count.
- `message_cancelled` — body includes the reason.
- `message_failed` — body includes the error code and a short reason.

If called after the message is already complete, the server replays a synthetic event stream that ends with `message_complete` immediately. Reconnects using `Last-Event-ID` resume from the last emitted event.

**Auth**: Same as message read.

#### `POST /workspaces/{workspaceId}/chat-sessions/{sessionId}/messages/{messageId}/cancel`

**Purpose**: Cancel a streaming assistant message.

**Outputs**: 202. The message transitions to status `cancelled` within one second; tokens already streamed are preserved.

**Auth**: The session's creator or an Owner/Editor with access.

**Errors**: `conflict` (message already `complete`, `cancelled`, or `failed`).

#### `POST /workspaces/{workspaceId}/chat-sessions/{sessionId}/messages/{messageId}/regenerate`

**Purpose**: Regenerate the last assistant message. The previous assistant message is retained as an alternate; a new assistant message is enqueued and streamed.

**Inputs**: Optional `scope_overrides`, optional `model_overrides`.

**Outputs**: 202 with the new assistant message id and a `stream_url`.

**Auth**: Editor (or session creator).

**Errors**: `business_rule_violation` (the message being regenerated is not the latest assistant turn in the session).

#### `POST /workspaces/{workspaceId}/chat-sessions/{sessionId}/messages/{messageId}/select-alternate`

**Purpose**: Mark a particular alternate as the active one for its `sequence` slot.

**Inputs**: `alternate_message_id`.

**Outputs**: Updated session message list.

**Auth**: Editor (or session creator).

#### `GET /workspaces/{workspaceId}/chat-sessions/{sessionId}/messages/{messageId}/retrieval`

**Purpose**: Get the `RetrievalRecord` for an assistant message — the exact items and excerpts that grounded the response.

**Outputs**: Retrieval record with `retrieval_strategy`, `query_text`, `retrieved_items[]` (each with kind, id, score, excerpt), `total_candidates`, `truncated`.

The first entry in `retrieved_items[]` is always a synthesized `kind="graph_context"` row (id `workspace_shape`) when the workspace is non-empty. Its `excerpt` is the rendered text of the graph-context grounding document — workspace-wide entity/edge totals plus per-type counts and named exemplars from `filter_options_repo.summarize_workspace_graph`. The pipeline service constructs the matching `ChatDocument` with id `graph_context:workspace_shape` and prepends it to the documents passed to Cohere so the LLM has authoritative ground truth for typed-aggregation questions ("how many", "list all", "count by"). Empty workspaces skip the row entirely so the refusal short-circuit still fires. See [`techstack.md`](techstack.md) Grounded Chat section and **TD-015** for the long-term replacement with deterministic traversal handlers.

**Auth**: Member (subject to share visibility).

**Errors**: `not_found` (message was `refused` and has no retrieval record).

#### `POST /workspaces/{workspaceId}/chat-sessions/{sessionId}/messages/{messageId}/report`

**Purpose**: Report a bad answer (low-quality, hallucinated, miscited). Recorded for offline review.

**Inputs**: `reason` (enum: `hallucination`, `bad_citation`, `refused_incorrectly`, `harmful`, `other`), optional `notes`.

**Outputs**: 204.

**Auth**: Any member who can see the message.

#### `POST /workspaces/{workspaceId}/chat-sessions/{sessionId}/export` (P1+)

**Purpose**: Export a session as Markdown with citations preserved as footnotes.

**Inputs**: `format` (`markdown` only in P1).

**Outputs**: 200 with `text/markdown` body or 202 with a job id for very long sessions.

**Auth**: Member.

#### "Ask about this" convenience

`POST /workspaces/{workspaceId}/chat-sessions` accepts an optional `seed_context` payload that pre-scopes the session to a selection:

- `kind` (`note | entity | subgraph`).
- `id` (UUID of the note or entity), or `entity_ids[]` for `subgraph`.
- For `subgraph`: `depth` (integer, default 1).

When `seed_context` is provided, the server computes the equivalent `scope` (e.g., for `entity`, expands to the entity's N-hop neighborhood) and stores it on the new session, then runs the optional `seed_message` against that scope.

---

### Snapshots

#### `GET /workspaces/{workspaceId}/snapshots`

**Purpose**: List snapshots.

**Outputs**: Paginated snapshots with stats and review state.

**Auth**: Member.

#### `POST /workspaces/{workspaceId}/snapshots`

**Purpose**: Create a snapshot (mark the working graph as reviewed).

**Inputs**: `name`, optional `description`.

**Outputs**: The created snapshot.

**Auth**: Editor.

**Errors**: `conflict` (name already used), `business_rule_violation` with message **Cannot snapshot an empty graph** when the workspace has zero entities.

#### `GET /workspaces/{workspaceId}/snapshots/{snapshotId}`

**Purpose**: Get a snapshot's metadata and stats.

**Outputs**: Snapshot.

**Auth**: Member.

#### `POST /workspaces/{workspaceId}/snapshots/{snapshotId}/review`

> **Sprint 5b — implemented**. Single-row-per-snapshot semantics: re-submitting overwrites.

**Purpose**: Record a review decision for a snapshot.

**Inputs**: `status` (`approved | rejected | needs_changes`), optional `rationale` (≤2000 chars). The legacy `decision` field is accepted as an alias for `status` and accepts the same enum values.

**Outputs**: `{ review: { snapshot_id, status, rationale, reviewer_user_id, created_at, updated_at } }`.

**Auth**: Member.

**Notes**: `needs_changes` denotes a soft block (reviewer wants edits before approval) and is treated the same as no decision for persistence-gating purposes. Implementations may still accept the legacy `approved | rejected` two-state form until TD-014 lands the third state end-to-end; see [tech_debt.md](../sprints/tech_debt.md).

#### `DELETE /workspaces/{workspaceId}/snapshots/{snapshotId}`

**Purpose**: Delete a snapshot. Does not affect external graph databases.

**Outputs**: 204.

**Auth**: Owner.

**Errors**: `business_rule_violation` (active PersistenceJob).

---

### External Graph Targets

#### `GET /workspaces/{workspaceId}/targets`

**Purpose**: List external graph targets.

**Outputs**: Paginated targets with last test status and timestamps.

**Auth**: Member.

#### `POST /workspaces/{workspaceId}/targets`

**Purpose**: Create a new external target.

**Inputs**: `name`, `kind` (`neo4j | postgres_age`), `connection_metadata` (host, port, database/graph), credential fields (will be encrypted and stored as a new ApiKey), `default_write_mode`.

**Outputs**: Target record (no secret returned).

**Auth**: Owner.

**Errors**: `validation_failed`, `conflict` (name taken).

#### `GET /workspaces/{workspaceId}/targets/{targetId}`

**Purpose**: Get a target's metadata.

**Outputs**: Target.

**Auth**: Member.

#### `PATCH /workspaces/{workspaceId}/targets/{targetId}`

**Purpose**: Update a target's name, default write mode, connection metadata, or credentials.

**Outputs**: Updated target.

**Auth**: Owner.

#### `DELETE /workspaces/{workspaceId}/targets/{targetId}`

**Purpose**: Remove a target.

**Outputs**: 204.

**Auth**: Owner.

**Errors**: `business_rule_violation` (active job).

#### `POST /workspaces/{workspaceId}/targets/{targetId}/test`

**Purpose**: Verify connectivity and required permissions without writing data.

**Outputs**: `status` (`ok | unreachable | unauthorized | permission_denied | unknown_error`), `details` (server version, missing constraints, etc.).

**Auth**: Owner.

---

### Persistence Jobs

#### `GET /workspaces/{workspaceId}/persistence-jobs`

**Purpose**: List persistence jobs.

**Query**: `status[]`, `target_id`, `snapshot_id`, pagination, sort.

**Outputs**: Paginated jobs.

**Auth**: Member.

#### `POST /workspaces/{workspaceId}/persistence-jobs`

**Purpose**: Start persisting a snapshot to a target.

**Inputs**:

- `snapshot_id`, `target_id`, `write_mode` (`upsert | replace`).
- For `replace`: `confirmation_token` returned from the dry-run step.
- Optional `include_provenance_subgraph` (boolean).

**Outputs**: 202 with `job_id` and `status_url`.

**Auth**: Owner.

**Errors**: `business_rule_violation` (snapshot rejected in review; target last_test_status != ok and `force` not set), `validation_failed`.

#### `POST /workspaces/{workspaceId}/persistence-jobs/dry-run`

**Purpose**: Compute the diff a persistence run would produce (nodes/edges to add, update, delete).

**Inputs**: Same as the create endpoint.

**Outputs**: `diff` summary (counts and a sampled list), `confirmation_token` (required for `replace` mode).

**Auth**: Owner.

#### `GET /workspaces/{workspaceId}/persistence-jobs/{jobId}`

**Purpose**: Get current state of a job.

**Outputs**: Job record with progress and failure reason if applicable.

**Auth**: Member.

#### `POST /workspaces/{workspaceId}/persistence-jobs/{jobId}/cancel`

**Purpose**: Request cancellation. Returns 202; the job transitions to `cancelled` within 10 seconds.

**Auth**: Owner.

---

### Generic Jobs and Streaming

These apply to any job (IngestionRun, PersistenceJob, large cascade delete).

#### `GET /jobs/{jobId}`

**Purpose**: Poll job state.

**Outputs**: Job record (`kind`, `status`, `progress`, timestamps).

**Auth**: Workspace member of the job's workspace.

#### `POST /jobs/{jobId}/cancel`

**Purpose**: Request cancellation.

**Outputs**: 202.

**Auth**: Editor or Owner (depending on job kind).

#### `GET /jobs/{jobId}/events`

**Purpose**: Subscribe to a real-time stream of progress events for the job. The endpoint replays the last ~200 events from the per-job Redis Stream (`XRANGE zkast:jobs:<jobId>:log`) immediately on connect, then tails the Redis pub/sub channel `zkast:jobs:<jobId>` for live messages — so a late subscriber sees recent history (Sprint 5b).

**Query**: `workspaceId` (UUID, required) — the workspace whose job this is. Used to scope pipeline-side authorization.

**Outputs**: `text/event-stream`. Each `data:` payload is a JSON object with a `type` field.

**Event types**:

- `stage_started` — `{ type, stage }`. Stage begins; one of `parsing`, `generating_notes`, `extracting_graph`, `building_graph`.
- `stage_progress` — `{ type, stage, percent, current, total, message? }`. Coarse-grained progress.
- `stage_completed` — `{ type, stage }`.
- `log` — `{ type, level: "info" | "warning" | "error", stage, message, data? }`. Human-readable line; durably persisted to `ingestion_run_logs` for replay via `GET .../ingestion-runs/{id}/logs`. Drives the pipeline-log drawer.
- `metric` — `{ type, name, value, stage, data? }`. Numeric metric for the drawer's count tickers and the Diagnostics latency series. Common `name`s: `entity_count`, `edge_count`, `note_count`, `tokens_consumed`, `evidence_spans_extracted`, `evidence_spans_linked`. Metrics are streamed only — they are intentionally **not** persisted to `ingestion_run_logs`.
- `warning` — `{ type, reason, ... }`. Reserved for top-level run warnings distinct from per-stage `log` warnings.
- `job_completed` — `{ type, status }`.
- `job_failed` — `{ type, reason, stage? }`.
- `job_cancelled` — `{ type, reason }`.

The wire format keeps comment lines (`: keepalive\n\n`) every 15 seconds so reverse proxies don't drop idle connections.

**Auth**: Workspace member.

---

### Settings and API Keys

#### `GET /workspaces/{workspaceId}/api-keys`

**Purpose**: List API key records (never secrets).

**Outputs**: Paginated key records with `kind`, `label`, `last_used_at`.

**Auth**: Owner.

#### `POST /workspaces/{workspaceId}/api-keys`

**Purpose**: Add a new API key.

**Inputs**: `kind` (`llm_cohere` | `north_bearer` | other supported kinds), `label`, `secret`, optional `metadata`. At most one `north_bearer` row per workspace; conflicts return HTTP 409 with a rotate/remove message.

**Outputs**: The record (no secret).

**Auth**: Owner.

#### `PATCH /workspaces/{workspaceId}/api-keys/{apiKeyId}`

**Purpose**: Update a key (rotate secret, change label/metadata).

**Inputs**: Any subset including a new `secret`.

**Outputs**: Updated record (no secret).

**Auth**: Owner.

#### `DELETE /workspaces/{workspaceId}/api-keys/{apiKeyId}`

**Purpose**: Remove a key.

**Auth**: Owner.

**Errors**: `business_rule_violation` (key in use by an active target or pipeline configuration).

#### `GET /workspaces/{workspaceId}/settings/pipeline`

**Purpose**: Get pipeline parameters.

**Outputs**: `chunk_size`, `max_notes_per_document`, `language`, `default_llm_provider`, `small_model`, `large_model`, `embed_model`, `rerank_model`, `include_provenance_subgraph_default`, `north_base_url` (empty string when unset). Legacy `north_bearer_token` values stored in older workspaces are stripped on read — callers must use the `north_bearer` API key instead.

**Auth**: Member (read), Owner (write).

#### `PATCH /workspaces/{workspaceId}/settings/pipeline`

**Purpose**: Update pipeline parameters (including `north_base_url`).

**Auth**: Owner.

#### `POST /workspaces/{workspaceId}/providers/north/test`

**Purpose**: Verify North HTTP connectivity for the workspace using saved `north_base_url` + decrypted `north_bearer` secret (or legacy pipeline token until migrated).

**Outputs**: `{ ok: true, agent_count }` on success; `{ error: { code, message } }` with non-2xx status when misconfigured or upstream errors.

**Auth**: Owner.

---

### Audit Log (P1+)

#### `GET /workspaces/{workspaceId}/audit-log`

**Purpose**: Browse the audit log.

**Query**: `actor_user_id`, `action`, `from`, `to`, pagination.

**Outputs**: Paginated AuditLogEntries.

**Auth**: Owner.

---

### Administration

Read-only diagnostics and cleanup affordances behind Settings → Diagnostics. All routes require Owner.

#### `GET /workspaces/{workspaceId}/ingestion-runs/{ingestionRunId}/logs`

> **Sprint 5b — implemented**. Reads the durable `ingestion_run_logs` table for one run.

**Query**: `limit` (1–500, default 200), `cursor` (opaque pagination token).

**Outputs**: `{ items: [{ id, ts, level, stage, message, data }], next_cursor }` — ordered ascending by `ts` so a streaming viewer can replay the run in time order.

**Auth**: Member.

#### `GET /admin/diagnostics`

> **Sprint 5b — implemented**.

**Purpose**: System-wide health snapshot for the Diagnostics page. Aggregates the arq queue depth, in-progress jobs, stalled documents (heartbeat older than `HEARTBEAT_STALE_THRESHOLD_S`), per-stage p50 / p95 latency from `ingestion_run_logs`, and a Redis hash-hygiene count (`zkast:job:*` entries in terminal status).

**Outputs**: `{ arq: { queue, in_progress }, stalled_documents: [...], latency_per_stage: { parsing: {...}, generating_notes: {...}, extracting_graph: {...} }, job_hashes: { total, terminal, safe_to_delete } }`.

**Auth**: Owner.

#### `POST /admin/cleanup-stale-job-hashes`

> **Sprint 5b — implemented**.

**Purpose**: Delete Redis job hashes (`zkast:job:*`) whose `status` is in a terminal state (`succeeded`, `failed`, `cancelled`). Refuses to touch any hash with a live (`running` / `queued`) status — that's the BUG-005 footgun this endpoint exists to avoid.

**Outputs**: `{ removed: integer, kept: integer }`.

**Auth**: Owner.

---

### Telemetry and Health

#### `GET /healthz`

**Purpose**: Liveness check (no auth).

**Outputs**: `{ "status": "ok" }`.

#### `GET /readyz`

**Purpose**: Readiness check; verifies DB, working graph, and (optionally) configured LLM provider reachability.

**Outputs**: Per-dependency status.

#### `GET /version`

**Purpose**: Return web tier version, pipeline service version, and external-graph contract version.

---

## Internal Contract (Web -> Pipeline)

This is **not** part of the public API. It is the contract between the web tier and the pipeline service, deployed together. Documented here so the contract is reviewable. All internal endpoints authenticate with the shared `X-Zkast-Internal-Token` and are bound to the internal network in self-hosted mode.

Workspace-scoped routes carry the workspace UUID in the path (`/internal/v1/workspaces/{workspaceId}/...`). The legacy unscoped form is retained for a handful of system-wide actions (Cohere probe, persistence jobs, generic jobs).

### Provider probes and ingestion

- `POST /internal/v1/providers/cohere/test` — Connectivity probe against Cohere (OpenAI-compat chat + native embed + rerank); uses plaintext `api_key` or decrypts `llm_cohere` for `workspace_id`.
- `POST /internal/v1/documents` — Multipart PDF upload (`workspace_id`, `file`, optional `replaces_document_id`); streams to local storage, inserts `Document` + `IngestionRun`, enqueues arq `parse_document`. Optional `Idempotency-Key` header (24h replay). Returns **202** with `document` + `job_id`. Sub-job `_job_id`s are stage-suffixed (`:parse`, `:notes`, `:graph`) to avoid the arq dedup collision documented in BUG-001.
- `DELETE /internal/v1/documents/{documentId}?workspace_id=&cascade=&force=` — `cascade` is `document_only` (default) or `exclusive_derivatives` (removes notes exclusive to the document, then runs the orphan-cleanup sweep). `force=true` cancels any active ingestion runs first (BUG-document-busy). Returns **204**. Responds **409** with `error.code: business_rule_violation` when ingestion is active and `force` is not set.
- `GET /internal/v1/documents/{documentId}/delete-preview?workspace_id=&cascade=` — Returns counts of exclusive vs shared notes and touched entities/relationships for the delete modal.
- `POST /internal/v1/ingestion-runs` — Body `{ "document_id", "from_stage" }` where `from_stage` is `parsing` / `generating_notes` / `extracting_graph`. Returns **202** with `document`, `ingestion_run_id`, `job_id`. **409** `business_rule_violation` if the document is mid-pipeline.
- `POST /internal/v1/extract/atomic-notes` — JSON `{ "workspace_id", "episode_ids": [...] }`; episodes must share one document + ingestion run. Restarts the run with an episode filter.

### Notes

- `GET/POST/PATCH/DELETE /internal/v1/notes` — Atomic notes CRUD, list filters (`q`, `tags`, `document_id`, `origin`, `is_user_edited`, `sort`, pagination); `POST .../notes/{id}/merge`, `POST .../notes/{id}/split`, `POST .../notes/{id}/unmerge` (Sprint 5b — restores victim from `merge_audit_log`), link create/delete under `.../notes/{id}/links`.
- **Merge body** — `{ "other_note_id": "<uuid>", "field_selection": { "title": "survivor"|"other", "body": "...", "tags": "..." } }` (per-field winner; merged tags are the union of both notes' tags).
- **Split body** — `{ "passage": "<verbatim substring of parent body>", "new_title": "..." }`.
- `GET /internal/v1/workspaces/{workspaceId}/notes/tags` — Distinct tags with counts (Sprint 5c). Backs the tag-picker combobox.

### Graph

- `GET /internal/v1/workspaces/{workspaceId}/graph?...` — List the working graph for a workspace (view, seeds, depth, filters).
- `GET /internal/v1/workspaces/{workspaceId}/graph/entities/{entityId}?neighbor_depth=&neighbor_limit=` — Entity detail including `incident_relationships` (Sprint 5).
- `PATCH /internal/v1/workspaces/{workspaceId}/graph/entities/{entityId}` — Patch entity fields.
- `POST /internal/v1/workspaces/{workspaceId}/graph/entities/{entityId}/merge` — Merge with `field_selection`; writes a `merge_audit_log` row (Sprint 5b).
- `POST /internal/v1/workspaces/{workspaceId}/graph/entities/{entityId}/unmerge` — Restore victim from audit log (Sprint 5b).
- `DELETE /internal/v1/workspaces/{workspaceId}/graph/entities/{entityId}` — Delete entity.
- `GET /internal/v1/workspaces/{workspaceId}/graph/search?q=&limit=` — Graphiti hybrid search (Sprint 5b). **Replaces the prior unscoped `POST /internal/v1/graph/search` stub.**
- `GET /internal/v1/workspaces/{workspaceId}/graph/entities/{entityId}/evidence?limit=&offset=` — LangExtract-derived evidence rows (Sprint 5c).
- `GET /internal/v1/workspaces/{workspaceId}/graph/types` — Entity + edge type counts (Sprint 5c). Backs the filter pickers.
- `GET /internal/v1/workspaces/{workspaceId}/graph/entities/search-typeahead?q=&limit=` — Cheap ILIKE typeahead (Sprint 5c). Distinct from the heavier `/graph/search`.
- `POST /internal/v1/workspaces/{workspaceId}/graph/cleanup-orphans` — Manual orphan sweep (Sprint 5b). Preserves `is_user_edited = true` entities and `origin = manual` edges.
- `POST /internal/v1/workspaces/{workspaceId}/graph/relationships` — Create manual relationship.
- `PATCH /internal/v1/workspaces/{workspaceId}/graph/relationships/{relationshipId}` — Update (or end via `valid_to`).
- `DELETE /internal/v1/workspaces/{workspaceId}/graph/relationships/{relationshipId}` — Soft-end.

### Snapshots

- `GET/POST /internal/v1/workspaces/{workspaceId}/snapshots` — List / create.
- `GET /internal/v1/workspaces/{workspaceId}/snapshots/{snapshotId}` — Detail + stats.
- `POST /internal/v1/workspaces/{workspaceId}/snapshots/{snapshotId}/review` — Record/update a `SnapshotReview` row (Sprint 5b). Body: `{ status, rationale? }` with `status` ∈ `approved | rejected | needs_changes`.
- `DELETE /internal/v1/workspaces/{workspaceId}/snapshots/{snapshotId}` — Delete.

### Persistence

- `POST /internal/v1/persistence-jobs` — Start a persistence job for a snapshot/target pair.

### Chat

- `POST /internal/v1/workspaces/{workspaceId}/chat/turns` — Run a single chat turn: retrieve, call Cohere Chat with grounding, stream tokens and citations. Returns an SSE stream consumed by the web tier and proxied to the browser (Sprint 6).
- `POST /internal/v1/workspaces/{workspaceId}/chat/turns/{turnId}/cancel` — Cancel an in-flight chat turn (Sprint 6).

### Jobs and ingestion observability

- `GET /internal/v1/jobs/{jobId}?workspace_id=` — Poll job hash state.
- `GET /internal/v1/jobs/{jobId}/events?workspace_id=` — SSE for that job: **replays from Redis Stream `zkast:jobs:<jobId>:log` (XRANGE last ~200) then tails the pub/sub channel `zkast:jobs:<jobId>`** (Sprint 5b). Emits `log`, `metric`, `stage_*`, `job_*` event types (see the public `GET /jobs/{jobId}/events` section above for the schema).
- `GET /internal/v1/workspaces/{workspaceId}/ingestion-runs/{ingestionRunId}/logs?limit=&cursor=` — Durable log read from `ingestion_run_logs` (Sprint 5b).

### North Agents (conversation source)

- `POST /internal/v1/workspaces/{workspaceId}/north/agents/sync` — Upsert local `north_agents` rows from the configured North instance (`pipeline_settings.north_base_url` + encrypted `north_bearer` API key, with legacy `north_bearer_token` in pipeline JSON still honored until migrated).
- `POST /internal/v1/workspaces/{workspaceId}/north/test-connection` — Calls North `GET /v1/agents` with workspace credentials; returns `{ ok, agent_count }` or upstream error payload.
- `GET /internal/v1/workspaces/{workspaceId}/north/agents` — List registered agents for the workspace.
- `GET /internal/v1/workspaces/{workspaceId}/north/agents/{agentId}/conversations?refresh=` — When `refresh=true`, list conversations from North and upsert `north_conversation_cache`; when false, return rows from the local cache only.
- `GET /internal/v1/workspaces/{workspaceId}/north/agents/{agentId}/conversations/{conversationId}/cache` — Return cached payload for one conversation id.
- `POST /internal/v1/workspaces/{workspaceId}/north/agents/{agentId}/conversations/{conversationId}/import` — Create a `north_conversation` document, persist transcript JSON to storage, enqueue `parse_document` (transcript → episodes → notes → graph). Dedupes on transcript checksum.
- `POST /internal/v1/workspaces/{workspaceId}/north/agents/{agentId}/dream` — Enqueue `run_dreaming_job` (per-agent memory evolution with audited mutations).

### Administration

- `GET /internal/v1/admin/diagnostics` — Queue depth, in-progress jobs, stalled documents, per-stage p50/p95, hash hygiene (Sprint 5b).
- `POST /internal/v1/admin/cleanup-stale-job-hashes` — Delete `zkast:job:*` Redis hashes in terminal status only (Sprint 5b). Never touches live jobs.

## Rate Limits

- **P0 self-hosted**: No enforced rate limits; only the LLM provider's own limits apply. A per-session lock prevents two simultaneous streaming assistant turns in the same chat session.
- **P1 self-hosted multi-user**: Per-workspace ingestion concurrency limit and per-workspace chat-turn concurrency limit, both configurable; defaults: 4 documents in flight and 8 chat turns in flight.
- **P2 SaaS**: Per-tenant tiered limits on uploads/day, LLM tokens/day, concurrent jobs, and chat messages/day.

## Backwards Compatibility Commitments

- Endpoints, fields, and enum values added in a minor release will not break existing clients.
- Removing a field or changing the type of a field requires a new major version (`/v2`).
- Error codes are stable across minor versions; new codes may be added.

## Related Specifications

- [datamodel.md](datamodel.md) — Underlying entities and constraints these APIs surface.
- [userstories.md](userstories.md) — Stories these endpoints satisfy.
- [uiux.md](uiux.md) — UI flows that consume these endpoints.
- [techstack.md](techstack.md) — How these endpoints are implemented and deployed.
