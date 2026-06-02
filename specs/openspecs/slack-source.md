# Slack Source & Generalized Memory Sources Specification

## Overview

zkast ingests **Slack** channel conversations as a first-class source alongside PDFs and North agent transcripts. A connected **Slack channel** defines a **memory isolation boundary** equivalent to the existing per-agent boundary: derived episodes, atomic notes, links, graph artifacts, retrieval indexes, and wiki spaces default to a single channel unless explicitly scoped otherwise.

This specification has two coupled parts:

1. **Memory Sources generalization** — the existing North-specific agent registry is generalized into a provider-neutral **memory source** concept so Slack (and future providers) reuse the same isolation, provenance, retrieval, and wiki machinery without source-specific forks.
2. **Slack source** — a new provider that authenticates via Slack OAuth, lists channels, ingests channel conversations and their threads, and feeds the shared ingestion spine (episodes → notes → graph → wiki).

A Slack **channel** maps to one memory source (the isolation boundary). A Slack **thread** (a root message plus its replies) maps to one ingestion **document** under that source, mirroring how a North conversation maps to one document under an agent.

## Requirements

### Functional Requirements

- **FR-1**: A workspace can connect to a Slack workspace via **OAuth**, granting zkast a stored credential sufficient to list channels, read channel history, and read thread replies.
- **FR-2**: Operators can **register** Slack channels as local memory sources; each source row stores provider, external channel id, display metadata, import defaults, and optional incremental sync state.
- **FR-3**: Operators can **list** channels available to the connected Slack workspace and see which are already registered.
- **FR-4**: Operators can **list** and **fetch** threads/conversations for a registered channel; fetched payloads are **cached** for replay, debugging, and re-import under different filters.
- **FR-5**: Operators can **import** a Slack thread (or a batch of threads in a channel) into the standard ingestion spine: a compatibility **document** row plus **episodes** segmented from messages using configurable **message-class filters** and **segmentation mode**.
- **FR-6**: **Episodes** and **atomic notes** created from Slack sources carry **source provenance** (the internal memory source id) matching the owning channel.
- **FR-7**: The system reuses the existing **notes → graph → embeddings → wiki** pipeline for Slack documents without source-specific branches beyond parsing.
- **FR-8**: Operators can generate an **agent/source-scoped wiki** for a Slack channel, summarizing knowledge derived from that channel's threads.
- **FR-9**: **Retrieval and chat** flows accept an optional **source scope** so naive-RAG, graph, and hybrid modes do not blend artifacts across channels.
- **FR-10**: Re-importing the same thread is **idempotent** by content: unchanged threads do not create duplicate knowledge; changed threads are detected and re-ingested.

### Generalization Requirements

- **FR-G1**: The existing per-agent registry (currently North-only) is generalized to a provider-neutral **memory source** registry that supports providers `north` and `slack` (and future providers) under a single uniqueness model `(workspace_id, provider, external_id)`.
- **FR-G2**: Existing North data continues to function unchanged: prior agents, documents, episodes, notes, embeddings, graphs, and wiki spaces remain valid and correctly scoped after generalization.
- **FR-G3**: All references that previously meant "agent" (isolation boundary, graph naming, wiki scope, retrieval scope, dashboard grouping) are reinterpreted as "memory source" without changing behavior for North.

### Non-Functional Requirements

- **NFR-1**: **Isolation** — any query listing notes, episodes, links, or retrieval hits for a Slack memory source MUST filter by the internal source id when a source scope is active.
- **NFR-2**: **Immutability** — ingestion and enrichment MUST NOT replace immutable Slack message source text; only derived fields may change.
- **NFR-3**: **Security** — Slack OAuth tokens are secrets; only server-side services persist or use them, stored with the same encryption mechanism as other workspace credentials.
- **NFR-4**: **Backward compatibility** — the generalization migration MUST be reversible and MUST NOT break existing PDF or North ingestion.
- **NFR-5**: **Rate-limit resilience** — Slack API access MUST tolerate Slack rate limiting (pagination, retry/backoff, partial-progress reporting) without corrupting partially imported state.

## Data Model

### Memory Source (generalized)

**Purpose**: Provider-neutral local registration of an external conversation source; anchor for isolation, provenance, and incremental sync. Generalizes the prior North agent registry.

**Fields:**

- `id` (UUID, PK): Internal source identifier (the value used as the isolation/scope key elsewhere).
- `workspace_id` (UUID, FK): Owning workspace.
- `provider` (text, required): Provider discriminator — `north` | `slack` (extensible).
- `external_id` (text, required): Provider-native identifier (North agent id, or Slack channel id).
- `display_name` (text): Human label (agent display name, or Slack channel name).
- `import_settings` (JSONB): Message-class inclusion/exclusion defaults, segmentation mode, provider-specific options (e.g. include bot messages, include threads only).
- `sync_cursor` (text, nullable): Opaque cursor/timestamp for incremental listing.
- `provider_metadata` (JSONB, nullable): Provider-specific descriptive fields (e.g. Slack channel topic, is_private, member count).
- `created_at`, `updated_at` (timestamptz).

**Constraints:**

- Unique `(workspace_id, provider, external_id)`.

**Compatibility:**

- The internal source id continues to populate the same provenance columns (`agent_id`) on documents, episodes, atomic notes, retrieval embeddings, entities, relationships, and wiki spaces. Renaming of that column is out of scope for this sprint; the column semantics are widened to "owning memory source".

### Slack Connection

**Purpose**: Stores the per-workspace Slack OAuth grant used to call Slack APIs.

**Fields:**

- `workspace_id` (UUID, FK): Owning workspace.
- `slack_team_id` (text): Connected Slack workspace/team identifier.
- `slack_team_name` (text, nullable): Display name of the connected Slack workspace.
- `authed_scopes` (text array): Scopes granted by the OAuth install.
- `installed_at`, `updated_at` (timestamptz).

**Secret storage:**

- The OAuth access token is stored as an **encrypted workspace credential** (same mechanism as other provider tokens), keyed by a provider credential kind for Slack, with at most one active Slack credential per workspace.

**Constraints:**

- At most one Slack connection per workspace.

### Slack Conversation Cache

**Purpose**: Raw Slack thread/channel payloads for debugging and reprocessing.

**Fields:**

- `id` (UUID, PK).
- `workspace_id`, `source_id` (FKs): Owning workspace and memory source (channel).
- `external_conversation_id` (text): Stable thread identifier (channel id + root message timestamp).
- `payload` (JSONB): Normalized or raw thread payload (root message + replies).
- `fetched_at` (timestamptz).

**Constraints:**

- Unique `(source_id, external_conversation_id)`.

### Document (extended)

**Additional values:**

- `source_kind` (text): Adds `slack_conversation` to the allowed set (`pdf` | `north_conversation` | `slack_conversation`).
- `agent_id` (UUID, FK): Required when `source_kind = slack_conversation` (the owning memory source / channel).
- `external_conversation_id` (text, nullable): Slack thread identifier for dedup and per-thread memory stats.
- `source_metadata` (JSONB): Channel name, thread root author/timestamp, permalink, filter snapshot, ingest content hash.
- `raw_transcript_json` (JSONB, nullable): Full normalized messages for parsing (reused from North).

**Constraints:**

- The mime/source-kind check is extended so `slack_conversation` documents use the JSON transcript artifact mime type.
- `source_kind = slack_conversation` ⇒ `agent_id` (owning memory source) NOT NULL.

### Episode (extended)

**Values:**

- `kind` (text): Adds `slack_message` and `slack_turn_window` to the allowed set.
- `agent_id` (UUID, nullable FK): Copied from the document's owning memory source.

### Retrieval Embedding / Entities / Relationships / Wiki Spaces

- No new columns. Existing `agent_id` provenance is reused as the memory-source scope for Slack-derived rows.

## Business Rules

### Rule: Channel ownership

**Description**: A Slack thread import MUST be associated with exactly one registered memory source whose provider is `slack`.

**Applies To**: Document creation, episode generation, note generation.

**Validation**: `source_kind = slack_conversation` ⇒ `agent_id` NOT NULL and the referenced source belongs to the same workspace and has provider `slack`.

### Rule: Thread = document, channel = boundary

**Description**: Each imported Slack thread becomes one document; all documents for a channel share the channel's memory source id, so notes/graph/wiki aggregate at the channel level.

**Applies To**: Import handler, wiki scoping, retrieval scoping.

### Rule: Source isolation

**Description**: Notes, links, and retrieval results MUST NOT blend across different memory sources when a source scope is active. Link suggestions MUST NOT connect notes from different sources.

**Applies To**: Note generation, link insertion, retrieval, wiki generation.

### Rule: Token confidentiality

**Description**: Slack OAuth tokens are never returned to clients and never logged; only the connected team name and granted scopes are surfaced.

**Applies To**: Connection status endpoints, logs.

## User Flows

### Flow: Connect Slack workspace

**Trigger**: Operator opens Sources/Settings and chooses "Connect Slack".

**Preconditions:**

- A Slack app is configured with the required scopes and redirect URL.

**Steps:**

1. System initiates the Slack OAuth authorization request and redirects the operator to Slack.
2. Operator approves the requested scopes in Slack.
3. Slack redirects back with an authorization code.
4. System exchanges the code for an access token, stores it encrypted, and records the connected team name and granted scopes.
5. Operator sees a connected state with the Slack workspace name.

**Success Outcome**: Workspace has an active, encrypted Slack credential and can list channels.

**Error Outcomes**: User denies authorization, scope mismatch, expired/invalid code, or state mismatch — operator sees an actionable error; no partial credential is stored.

### Flow: Register channel as a memory source

**Trigger**: Operator browses available Slack channels and chooses one to track.

**Steps:**

1. System lists channels the connected app can access.
2. Operator selects a channel.
3. System upserts a local memory source row with provider `slack`, the channel id as `external_id`, the channel name as display name, and default import settings.

**Success Outcome**: The channel appears as a memory source with import defaults and zero imported threads.

### Flow: Import channel threads

**Trigger**: Operator selects a registered channel and confirms import (all threads, or a selected subset).

**Steps:**

1. System fetches channel history and, for each root message, its thread replies (using cache when fresh).
2. For each thread, system normalizes messages, computes an ingest content hash, and skips threads already imported with an unchanged hash.
3. For each new/changed thread, system creates a `slack_conversation` document, persists the normalized transcript and metadata, and enqueues the standard parse → notes → graph stages.
4. Operator monitors job progress per thread (or per batch).

**Success Outcome**: Episodes, notes, and graph artifacts scoped to the channel's memory source; channel-scoped wiki can then be generated.

**Error Outcomes**: Rate limiting (system backs off and resumes), empty thread after filters (skipped with a clear note), auth expiry (operator prompted to reconnect).

### Flow: Generate channel wiki

**Trigger**: Operator triggers wiki generation for a Slack channel source.

**Steps:**

1. System creates or reuses a source-scoped wiki space for the channel.
2. Wiki generation reads only notes belonging to that memory source.
3. System produces wiki pages summarizing the channel's knowledge.

**Success Outcome**: A channel-scoped wiki reflecting only that channel's imported threads.

## Authorization

### Permission: Manage Slack integration

**Required Role**: Workspace member with settings/manage capability (same as configuring pipeline credentials today).

**Resource-Level**: Only the same workspace's Slack connection, sources, and caches.

**Enforcement**: Server routes verify workspace membership before initiating OAuth or calling Slack.

## Validation Rules

### Field: OAuth scopes

- **Required**: The granted scopes MUST include the minimum set required to list channels, read channel history, and read thread replies.
- **Custom Rules**: If a required scope is missing, registration/import is blocked with a message naming the missing capability.

### Field: import_settings.segmentation_mode

- **Required**: No — defaults apply when missing.
- **Allowed**: `message` (one episode per message) | `turn` (group a root and its replies into a turn window).

### Field: Slack channel selection

- **Required**: Yes for registration.
- **Custom Rules**: Archived or inaccessible channels are not registrable; private channels require the app to be a member.

## User Interface Requirements

### View: Sources / Slack connection (Settings)

**Purpose**: Connect or disconnect Slack and show connection status.

**Display Elements:**

- Connection status (connected team name, granted scopes, or "Not connected").
- Connect / Reconnect / Disconnect actions.

**States:** Not connected, Connecting, Connected, Error.

### View: Slack channels

**Purpose**: Browse available channels and register them as memory sources.

**Display Elements:**

- Channel list with name, visibility (public/private), and registered/not-registered indicator.

**Actions Available:**

- Register channel, open registered channel detail.

### View: Channel detail — Threads

**Purpose**: Browse cached/live threads, preview, and import.

**Actions Available:**

- Refresh thread list, preview a thread, import selected threads, open the resulting document pipeline status, generate channel wiki.

> Note: For this sprint (spec + scaffolding), UI views are specified but not implemented; the backend skeleton and migration land first.

## Edge Cases

### Case: Empty thread after filters

**Scenario**: All messages in a thread excluded by filters (e.g. only system/join messages).

**Expected Behavior**: Import skips the thread with a clear reason; no orphan document or episodes.

### Case: Duplicate import

**Scenario**: The same thread imported twice with no content change.

**Expected Behavior**: Idempotent — detected via ingest content hash; no duplicate notes or graph artifacts.

### Case: Token revoked / expired

**Scenario**: Slack token revoked between imports.

**Expected Behavior**: Calls fail with an auth error; operator is prompted to reconnect; no partial corruption.

### Case: Rate limited mid-import

**Scenario**: Slack returns rate-limit responses during a multi-thread import.

**Expected Behavior**: System backs off and resumes; already-imported threads remain valid; progress is reported.

### Case: Bot and app messages

**Scenario**: Channel contains bot/app-generated messages.

**Expected Behavior**: Inclusion governed by `import_settings`; default excludes pure system/join/leave noise while retaining human and meaningful bot content.

## Acceptance Criteria

- [ ] AC-1: A reversible migration generalizes the agent registry to provider-neutral memory sources, adds the `slack_conversation` source kind, `slack_message` / `slack_turn_window` episode kinds, a Slack connection record, a Slack conversation cache, and a Slack credential kind — without breaking existing PDF or North ingestion.
- [ ] AC-2: A workspace can complete the Slack OAuth connect flow and the stored token is encrypted and never returned to clients.
- [ ] AC-3: Channels can be listed and registered as memory sources with provider `slack`.
- [ ] AC-4: Importing a Slack thread produces a `slack_conversation` document and source-scoped episodes, then reuses the existing notes → graph pipeline.
- [ ] AC-5: Re-importing an unchanged thread is idempotent (dedup on ingest content hash).
- [ ] AC-6: A channel-scoped wiki generates from only that channel's notes.
- [ ] AC-7: Retrieval/chat honor a Slack source scope and do not blend across channels.
- [ ] AC-8: Existing North agents, imports, graphs, and wikis continue to work unchanged after generalization.

## Success Metrics

- An operator can complete connect → register channel → import threads → notes → channel wiki on a real (or fixture) Slack channel in a single workspace without manual SQL.

## Out of Scope (this sprint)

- Full web UI implementation (connect button, channel browser, thread import surface) — specified here, implemented in a follow-up sprint.
- Real-time Slack event subscriptions / continuous sync (initial scope is on-demand pull + incremental cursor).
- Column rename of `agent_id` → `source_id` across all tables (semantics widened now; physical rename deferred to avoid a large, risky migration mid-track).

## Related Specifications

- `specs/openspecs/north-agents-amem.md` — the North source this generalizes from; shared isolation/provenance model.
- `specs/openspecs/llm-wiki-memory.md` — wiki spaces and source/agent scope.
- `specs/datamodel.md` — core tables; `source_kind`, provenance columns.
- `specs/apis.md` — internal HTTP contract additions for Slack connect/list/import.
