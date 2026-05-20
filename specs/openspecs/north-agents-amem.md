# North Agents & A-MEM-Style Memory Specification

## Overview

zkast ingests **North** agent conversation histories as a first-class source alongside PDFs. Each **Agent** (North-backed) defines a strict **memory isolation boundary**: derived episodes, atomic memories (notes), links, graph artifacts, retrieval indexes, dreaming/evolution jobs, and evaluations default to a single selected Agent unless explicitly scoped otherwise.

This capability supports **A-MEM–style** memories: atomic notes enriched with salient **keywords**, categorical **tags**, a one-line **context** summary, typed **links** with explicit **reasons**, and optional **offline evolution** (“dreaming”) that may adjust derived fields on neighboring memories without mutating immutable source text.

## Requirements

### Functional Requirements

- **FR-1**: Operators can configure per-workspace **North connectivity** (base URL, bearer token) sufficient to call North’s Agents and Conversations APIs.
- **FR-2**: Operators can **register** North agents locally; each local agent row stores provider, external agent id, display metadata, import defaults, and optional **sync cursor** state.
- **FR-3**: Operators can **list** and **fetch** conversations for a registered agent; full payloads are **cached** for replay, debugging, and re-import with different filters.
- **FR-4**: Operators can **import** a conversation into the standard ingestion spine: a compatibility **document** row plus **episodes** segmented from transcript messages using configurable **message-class filters** and segmentation mode (message, turn window, or hybrid defaults).
- **FR-5**: **Episodes** and **atomic notes** created from North sources carry **agent provenance** (`agent_id`) matching the owning agent.
- **FR-6**: **Note links** created during ingestion or dreaming may include **link reason** text and **link strength**; links must not connect notes belonging to **different** agents (unless a future cross-agent research mode is explicitly enabled).
- **FR-7**: After note generation, the system may run an **A-MEM enrichment** step that fills **memory keywords**, **memory context**, and augments **tags** using an LLM, without overwriting original note body sourced from episodes.
- **FR-8**: Operators can trigger **dreaming** (batch, per agent): retrieve nearest neighbor notes **within the same agent**, obtain structured LLM decisions, persist **link** updates and **neighbor tag/context** adjustments, append **evolution history** on affected notes, and record **audit** rows per mutation.
- **FR-9**: **Retrieval and eval** flows accept an optional **agent scope** so Naive-RAG, graph, and hybrid modes do not blend artifacts across agents.
- **FR-10**: A **North-history evaluation dataset** exists with categorized questions (single-hop, multi-hop, temporal, tool provenance, unanswerable) to compare retrieval modes under agent scope.

### Non-Functional Requirements

- **NFR-1**: **Isolation** — any query listing notes, episodes, links, dreaming mutations, or retrieval hits for North work MUST filter by `agent_id` when an agent scope is active.
- **NFR-2**: **Immutability** — dreaming and enrichment must not replace immutable transcript or episode source text; only derived fields (tags, context, keywords, link metadata, strengths) may change.
- **NFR-3**: **Auditability** — each dreaming job records status and timing; each applied mutation is persisted for inspection and rollback analysis.
- **NFR-4**: **Security** — North tokens are treated as secrets; only server-side services persist or use them.

## Data Model

### North Agent

**Purpose**: Local registration of an external North agent; anchor for isolation and sync.

**Fields:**

- `id` (UUID, PK): Internal agent identifier (`agent_id` elsewhere).
- `workspace_id` (UUID, FK): Owning workspace.
- `external_agent_id` (text, required): North agent id.
- `provider` (text, default `north`): Provider discriminator for future sources.
- `display_name` (text): Human label.
- `import_settings` (JSONB): Message-class inclusion/exclusion defaults, segmentation mode (`message` | `turn` | `window`), tool/citation handling flags, optional date/type filters.
- `sync_cursor` (text, nullable): Opaque cursor for incremental conversation listing.
- `created_at`, `updated_at` (timestamptz).

**Constraints:**

- Unique `(workspace_id, provider, external_agent_id)`.

### North Conversation Cache

**Purpose**: Raw North conversation list/detail payloads for debugging and reprocessing.

**Fields:**

- `id` (UUID, PK).
- `workspace_id`, `agent_id` (FKs).
- `north_conversation_id` (text).
- `payload` (JSONB): Normalized or raw API payload.
- `fetched_at` (timestamptz).

**Constraints:**

- Unique `(agent_id, north_conversation_id)`.

### Document (extended)

**Purpose**: Compatibility artifact for all ingestion sources.

**Additional fields:**

- `source_kind` (text): `pdf` | `north_conversation`.
- `agent_id` (UUID, nullable FK): Required when `source_kind = north_conversation`.
- `north_conversation_id` (text, nullable).
- `north_metadata` (JSONB): Titles, types, timestamps, filter snapshot, message index.
- `raw_transcript_json` (JSONB, nullable): Full normalized messages for parsing.

**Constraints:**

- Check constraint tying `mime_type` / `source_kind` to allowed combinations (PDF vs North transcript artifact).

### Episode (extended)

**Fields:**

- `agent_id` (UUID, nullable FK): Copied from document/agent for North-derived rows; null for legacy PDF-only rows.
- `kind` (text): Adds `north_message`, `north_turn_window`, `north_tool_event` in addition to existing kinds.

### Atomic Note (extended)

**Fields:**

- `agent_id` (UUID, nullable FK): Set for North-derived generated notes.
- `memory_context` (text, nullable): One-sentence contextual description.
- `memory_keywords` (text array): Salient concepts.
- `evolution_history` (JSONB, default empty array): Append-only audit of dreaming-driven changes.
- `dreaming_touched_at` (timestamptz, nullable): Last time dreaming adjusted derived fields.

### Note Link (extended)

**Fields:**

- `link_reason` (text, nullable): LLM or operator explanation for the edge.
- `link_strength` (float, default 1.0): Relative weight for retrieval and UI.

### Dream Job

**Purpose**: Batch dreaming run for one agent.

**Fields:**

- `id`, `workspace_id`, `agent_id`, `status`, `stats` (JSONB), `failure_reason`, `started_at`, `ended_at`.

### Dream Job Mutation

**Purpose**: Per-note audit row for an applied dreaming change.

**Fields:**

- `id`, `dream_job_id`, `note_id`, `mutation_type` (text), `payload` (JSONB), `created_at`.

### Retrieval Embedding (extended)

**Fields:**

- `agent_id` (UUID, nullable): Propagated for North raw chunks and future note embeddings to enforce agent-scoped ANN filters.

## Business Rules

### Rule: Agent ownership

**Description**: A North conversation import MUST be associated with exactly one registered `north_agents` row.

**Applies To**: Document creation, episode generation, note generation.

**Validation**: `source_kind = north_conversation` ⇒ `agent_id` NOT NULL and agent belongs to same workspace.

### Rule: Link isolation

**Description**: `note_links` MUST NOT connect two notes with different non-null `agent_id` values.

**Applies To**: Link insertion from LLM suggestions and dreaming.

**Validation**: Application checks both endpoints before insert.

### Rule: Dreaming immutability

**Description**: Dreaming may update tags, `memory_context`, `memory_keywords`, link metadata, and strengths; it MUST NOT change episode text or replace immutable transcript-derived note bodies.

**Applies To**: Dreaming worker.

**Validation**: Updates restricted to allowed columns; mutations logged.

## User Flows

### Flow: Register North agent

**Trigger**: Operator opens Agents area and chooses “Sync agents from North”.

**Steps:**

1. System validates North credentials.
2. System fetches remote agents and upserts local `north_agents` rows.
3. Operator sees registered agents with display names and external ids.

**Success Outcome**: Local agent list matches selected North agents.

**Error Outcomes**: Auth failure, network error — operator sees actionable error; no partial isolation breach.

### Flow: Import conversation

**Trigger**: Operator selects a conversation and confirms import.

**Steps:**

1. System fetches full conversation if not cached; stores/updates cache.
2. System creates a `documents` row (`north_conversation`) and persists raw transcript JSON + metadata.
3. System enqueues parsing → notes → graph stages identical to PDFs.
4. Operator monitors job log until completion.

**Success Outcome**: Episodes, notes, and graph scoped to the agent.

### Flow: Run dreaming

**Trigger**: Operator triggers dreaming for one agent.

**Steps:**

1. System creates `dream_jobs` row in `running` state.
2. For capped batches of notes in that agent, system finds neighbors (embedding similarity or equivalent), calls LLM for structured decisions, applies allowed mutations, appends evolution history, inserts link rows with reasons.
3. System marks job `complete` with stats `{notes_considered, links_added, neighbors_updated}`.

**Error Outcomes**: Job `failed` with `failure_reason`; no silent cross-agent writes.

## Authorization

### Permission: Manage North integration

**Required Role**: Workspace member with settings/manage capability (same as pipeline credentials today).

**Resource-Level**: Only same workspace’s agents and caches.

**Enforcement**: Server routes verify workspace membership before internal pipeline calls.

## Validation Rules

### Field: import_settings.message_classes

- **Required**: No — defaults apply when missing.
- **Custom Rules**: At least one content-bearing class should remain enabled for non-empty imports.

### Field: North bearer token

- **Required**: Yes, for sync/import routes that call North.
- **Length**: Reasonable max stored encrypted or via existing secret mechanism (implementation-specific).

## User Interface Requirements

### View: Agents (primary nav)

**Purpose**: Register agents, open agent detail, configure import defaults, trigger sync/import and dreaming.

**Display Elements:**

- Agent list with provider, name, last sync time.
- Status indicators for North connectivity.

**Actions Available:**

- Sync agents, open agent detail, trigger dreaming.

### View: Agent detail — Conversations

**Purpose**: Browse cached or live conversations, preview, import.

**Actions Available:**

- Refresh list, import selected, open imported document pipeline status.

## Edge Cases

### Case: Empty transcript after filters

**Scenario**: All messages excluded by filters.

**Expected Behavior**: Ingestion fails fast with clear validation message; no orphan episodes.

### Case: Duplicate import

**Scenario**: Same conversation imported twice.

**Expected Behavior**: New document/run or idempotent policy documented; no cross-agent duplication.

## Acceptance Criteria

- [ ] AC-1: Migrations add agent, North cache, document provenance, episode kinds, note enrichment, link metadata, dream audit, retrieval `agent_id` without breaking existing PDF ingestion.
- [ ] AC-2: Importing a North conversation produces agent-scoped episodes and notes.
- [ ] AC-3: Dreaming never writes links between different agents.
- [ ] AC-4: Eval runner accepts agent scope and ships a North-history YAML dataset describing categories and pattern-based scoring expectations.
- [ ] AC-5: Conversations expose a per-row sync status (not synced / synced / syncing / outdated) and re-import dedupes on ingest content hash.
- [ ] AC-6: Chat agent scope is selected through an agent picker, not a manual UUID entry, and the chat header surfaces the active memory boundary.
- [ ] AC-7: Dream jobs publish progressive telemetry (start, progress, link / neighbor patch events, completion or failure) on the shared job event stream and dock the pipeline log on the agent detail view.
- [ ] AC-8: Failed Dream jobs surface failure reason and recovery guidance in the Dream status card.

## Success Metrics

- Operator can complete register → import → notes → dreaming on a synthetic transcript fixture in a single workspace without manual SQL.

## Related Specifications

- `specs/datamodel.md` — core tables (should be updated to reference this extension).
- `specs/apis.md` — internal HTTP contract additions for North and dreaming.
