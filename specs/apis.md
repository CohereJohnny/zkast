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

**Query**: `q` (full-text), `tags[]`, `document_id`, `origin`, `is_user_edited`, `sort`, pagination.

**Outputs**: Paginated notes with summary fields (title, tags, updated_at, document_id).

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

---

### Knowledge Graph

#### `GET /workspaces/{workspaceId}/graph`

**Purpose**: Return the current working graph in a form suitable for the visualization layer.

**Query**:

- `view` (`overview` | `subgraph`): controls level of detail.
- For `subgraph`: `seed_entity_ids[]`, `depth` (default 2).
- Filters: `entity_types[]`, `edge_types[]`, `document_id`, `tag`, `valid_at` (timestamp).
- `node_limit` (default 5000, max 25000).

**Outputs**: `nodes[]` (id, type, name, summary, properties), `edges[]` (id, source, target, type, fact, valid_from, valid_to, confidence), `truncated` (boolean).

**Auth**: Member.

#### `GET /workspaces/{workspaceId}/graph/entities`

**Purpose**: List entities with filtering, used by the entities table view.

**Query**: `q`, `type`, `tag`, `document_id`, pagination, `sort`.

**Outputs**: Paginated entities.

**Auth**: Member.

#### `GET /workspaces/{workspaceId}/graph/entities/{entityId}`

**Purpose**: Get a single entity with full detail and provenance.

**Outputs**: Entity, neighbors summary, source notes, source episodes.

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

**Inputs**: `source_entity_id`, `target_entity_id`, `type`, optional `fact`, `valid_from`, `valid_to`, `properties`.

**Outputs**: The created relationship.

**Auth**: Editor.

**Errors**: `validation_failed` (e.g., type constraint violated).

#### `PATCH /workspaces/{workspaceId}/graph/relationships/{relationshipId}`

**Purpose**: Update a relationship's fields, including ending it by setting `valid_to`.

**Inputs**: Any subset of `type`, `fact`, `valid_from`, `valid_to`, `properties`.

**Outputs**: Updated relationship.

**Auth**: Editor.

#### `DELETE /workspaces/{workspaceId}/graph/relationships/{relationshipId}`

**Purpose**: Mark a relationship as ended (sets `valid_to = now()`). Hard-delete is not exposed unless the parent entity is being deleted.

**Outputs**: 204.

**Auth**: Editor.

#### `GET /workspaces/{workspaceId}/graph/search`

**Purpose**: Hybrid search over the working graph (semantic + keyword + graph traversal — Graphiti-backed).

**Query**: `q`, optional `seed_entity_id`, `limit`.

**Outputs**: Ranked list of entities, relationships, and notes with scores and a brief explanation.

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

**Errors**: `conflict` (name already used), `business_rule_violation` (graph is empty).

#### `GET /workspaces/{workspaceId}/snapshots/{snapshotId}`

**Purpose**: Get a snapshot's metadata and stats.

**Outputs**: Snapshot.

**Auth**: Member.

#### `POST /workspaces/{workspaceId}/snapshots/{snapshotId}/review`

**Purpose**: Record a review decision for a snapshot.

**Inputs**: `decision` (`approved | rejected`), optional `notes`.

**Outputs**: Review record.

**Auth**: Member.

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

**Purpose**: Subscribe to a real-time stream of progress events for the job.

**Outputs**: `text/event-stream`. Event types: `stage_started`, `stage_progress`, `stage_completed`, `warning`, `job_completed`, `job_failed`, `job_cancelled`.

**Auth**: Workspace member.

---

### Settings and API Keys

#### `GET /workspaces/{workspaceId}/api-keys`

**Purpose**: List API key records (never secrets).

**Outputs**: Paginated key records with `kind`, `label`, `last_used_at`.

**Auth**: Owner.

#### `POST /workspaces/{workspaceId}/api-keys`

**Purpose**: Add a new API key.

**Inputs**: `kind`, `label`, `secret`, `metadata`.

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

**Outputs**: `chunk_size`, `max_notes_per_document`, `language`, `default_llm_provider`, `small_model`, `large_model`, `include_provenance_subgraph_default`.

**Auth**: Member (read), Owner (write).

#### `PATCH /workspaces/{workspaceId}/settings/pipeline`

**Purpose**: Update pipeline parameters.

**Auth**: Owner.

---

### Audit Log (P1+)

#### `GET /workspaces/{workspaceId}/audit-log`

**Purpose**: Browse the audit log.

**Query**: `actor_user_id`, `action`, `from`, `to`, pagination.

**Outputs**: Paginated AuditLogEntries.

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

This is **not** part of the public API. It is the contract between the web tier and the pipeline service, deployed together. Documented here so the contract is reviewable.

- `POST /internal/v1/providers/cohere/test` — Connectivity probe against Cohere (OpenAI-compat chat + native embed + rerank); uses plaintext `api_key` or decrypts `llm_cohere` for `workspace_id`.
- `POST /internal/v1/documents` — Multipart PDF upload (`workspace_id`, `file`, optional `replaces_document_id`); streams to local storage, inserts `Document` + `IngestionRun`, enqueues Arq `parse_document`. Optional `Idempotency-Key` header (24h replay). Returns **202** with `document` + `job_id`.
- `DELETE /internal/v1/documents/{documentId}?workspace_id=` — Hard-delete document row, cascades episodes/runs; removes file from `ZKAST_STORAGE_ROOT`.
- `POST /internal/v1/ingestion-runs` — Body `{ "document_id", "from_stage": "parsing" }`; starts a new parse attempt (new `IngestionRun`) and enqueues `parse_document`.
- `POST /internal/v1/persistence-jobs` — Start a persistence job for a snapshot/target pair.
- `POST /internal/v1/graph/search` — Hybrid search delegated to Graphiti.
- `POST /internal/v1/extract/atomic-notes` — Run atomic-note generation on a set of episodes (used by manual re-runs).
- `POST /internal/v1/chat/turns` — Run a single chat turn: retrieve, call Cohere Chat with grounding, stream tokens and citations. Returns an SSE stream consumed by the web tier and proxied to the browser.
- `POST /internal/v1/chat/turns/{turnId}/cancel` — Cancel an in-flight chat turn.
- `GET /internal/v1/jobs/{jobId}` — Poll job hash state (requires `X-Zkast-Workspace-Id`).
- `GET /internal/v1/jobs/{jobId}/events` — SSE over Redis pub/sub for that job (requires `X-Zkast-Workspace-Id`).

All internal endpoints authenticate with the shared `X-Zkast-Internal-Token` and are bound to the internal network in self-hosted mode.

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
