# Live Ingestion Theater Specification

## Overview

Inspired by [MiroFish](https://github.com/666ghj/MiroFish) — where users watch a knowledge graph being built and simulations unfold in real time — zkast needs a **maximal, living observability surface** for ingestion. Sources (PDFs, North conversations, Slack channels, GraphRAG builds, Dream runs) should feel *alive*: stages lighting up, counters ticking, nodes and edges appearing on the graph, and a trace stream that reads like a control room rather than a monospace log.

This spec defines **WHAT** the experience must deliver. It does not prescribe React libraries, canvas engines, or animation frameworks.

## Goals

- **See ingestion unfold** — Users perceive parse → notes → extract → graph (and parallel paths like Slack import / GraphRAG) as a visible pipeline, not a black box.
- **Graph feels alive** — While extraction runs, the graph panel reflects growth (pulse, highlight, incremental refresh) without waiting for job completion.
- **Traces with personality** — Job output is visual: stage LEDs, throughput tiles, activity cards, and optional raw log — not only plain text.
- **Works everywhere ingestion runs** — Documents, Conversations, Slack, Agents (Dream), GraphRAG, Jobs dashboard share one theater component fed by the existing Redis job SSE channel.
- **Respect accessibility** — Reduced-motion mode falls back to static status + accessible list; blinking is decorative, never the only signal.

## Non-Goals (initial phases)

- Rebuilding the graph editor or replacing Sigma.
- n8n-style arbitrary pipeline topology editing (configurations remain a fixed linear chain).
- Full MiroFish-style multi-agent social simulation (out of scope for zkast ingestion).

## Requirements

### Functional Requirements

- **FR-1**: A **Pipeline Activity Theater** renders whenever the workspace has one or more subscribed active jobs.
- **FR-2**: The theater displays a **horizontal stage strip** with at least: Parse, Notes, Extract/Graph, Complete — plus extension slots for Slack import, GraphRAG indexing, Dream, Wiki generation.
- **FR-3**: Each stage exposes states: `idle`, `queued`, `running`, `done`, `error`, with distinct visual treatment (LED, pulse ring, checkmark, error glyph).
- **FR-4**: **Metric tiles** show live counters for `entity_count`, `edge_count`, `note_count`, `tokens_consumed`, and GraphRAG stats when emitted; values animate on change.
- **FR-5**: An **activity feed** shows the last N structured events as cards (timestamp, stage badge, human title, optional detail); raw monospace log remains available via a toggle.
- **FR-6**: Connecting lines between stages **pulse** when data flows (stage transition or progress event on the downstream stage).
- **FR-7**: The graph panel receives **activity signals** (via a workspace event bus) on graph-related metrics so it can pulse / throttled-refetch without full-page reload.
- **FR-8**: Backend emits **`activity`-typed SSE events** at meaningful moments (episode extracted, note batch created, GraphRAG workflow milestone) with structured payloads for card rendering.
- **FR-9**: Theater auto-opens when a job is registered (existing `requestOpenLogConsole` behavior); user can collapse or switch to log-only view; preference persists per browser.

### Non-Functional Requirements

- **NFR-1**: Theater must not block ingestion workers; all UI work is client-side over existing pub/sub.
- **NFR-2**: Graph refetch throttled to at most once every 3s during heavy metric bursts.
- **NFR-3**: Reduced-motion: disable pulse/particle animations; show static stage colors and numeric counters only.

## Event Model (SSE extensions)

Existing events (`log`, `metric`, `stage_started`, `stage_progress`, `stage_completed`, `job_completed`, `job_failed`) remain backward compatible.

New optional event:

### Activity Event

**Purpose**: Rich card in the activity feed and optional graph hints.

**Fields:**
- `type`: `"activity"`
- `stage`: pipeline stage id (e.g. `extracting_graph`)
- `kind`: `note_created` | `graph_batch` | `episode_parsed` | `slack_batch` | `graphrag_workflow` | `dream_link` | `generic`
- `label`: short human title (e.g. `+3 entities, +5 edges`)
- `detail`: optional longer text
- `data`: optional JSON (counts, ids, episode index, entity names sample)

**Business Rules:**
- Workers emit `activity` in addition to (not instead of) `record_log` for the same moment when the moment is user-visible.
- Activity events are not persisted to `ingestion_run_logs` (same as metrics).

## User Flows

### Flow: Upload PDF and watch ingestion

1. User uploads a PDF → job registered → theater expands.
2. Parse stage LED turns `running`; activity card "Parsing document…".
3. Notes stage activates; token counter ticks; cards show note batch progress.
4. Extract stage activates; entity/edge counters climb; graph panel pulses; optional cards per episode batch.
5. Complete → all stages `done`; graph settles; theater shows success summary card.

### Flow: Slack channel import

1. User starts import → Slack stage + Parse path visible.
2. Thread/message counts appear on metric tiles.
3. Downstream notes/graph stages activate as chained jobs run (or unified job spans stages).

### Flow: GraphRAG index build

1. GraphRAG stage strip slot activates.
2. Corpus export card → build_index card → stats card (entities, communities, reports).

## UI Requirements

### View: Pipeline Activity Theater (docked)

**Display Elements:**
- Stage strip with LEDs and inter-stage flow lines
- Metric tile row (entities, edges, notes, tokens)
- Activity feed (scrollable, newest at bottom or top — consistent with log)
- Header: job count, view toggle `[Theater | Log]`, collapse control

**States:**
- Idle (no jobs): collapsed header, hint text
- Active: expanded default, pulsing active stage
- Complete: success tint, optional auto-collapse after delay (user preference, default stay open)

### View: Graph panel (during ingestion)

**Display Elements:**
- Optional "Live ingestion" banner when extract stage running
- Canvas pulse overlay (border glow or subtle vignette) on graph metric events
- Throttled refetch on `entity_count` / `edge_count` changes

**Reduced motion:** banner + numeric badge only, no glow animation.

## Edge Cases

### Case: Multiple concurrent jobs

**Scenario**: Two documents ingesting simultaneously.
**Expected Behavior**: Stage strip shows union of active stages; metric tiles sum or show per-job breakdown on hover; activity feed interleaves events tagged with job id prefix.

### Case: Job failed mid-stage

**Scenario**: Extract fails on episode 5/10.
**Expected Behavior**: Failed stage shows error state; activity feed shows error card; graph retains partial entities from successful episodes.

### Case: User clears log buffer

**Scenario**: User clicks Clear in log view.
**Expected Behavior**: Theater metrics persist until job ends; activity feed clears locally; SSE replay policy unchanged (log view skips replay on navigation; theater may replay last 200 events on subscribe — configurable).

## Acceptance Criteria

- [ ] AC-1: Starting any ingestion job opens the docked theater with at least one stage in `running` within 5s.
- [ ] AC-2: Entity and edge counters update live during `extract_graph` without page refresh.
- [ ] AC-3: Graph panel visibly reacts (pulse or refetch) during extraction, throttled ≤1 refetch/3s.
- [ ] AC-4: User can switch between Theater and raw Log views without losing SSE subscription.
- [ ] AC-5: GraphRAG, Slack import, and Dream jobs appear in the stage strip with appropriate labels.
- [ ] AC-6: With `prefers-reduced-motion: reduce`, no pulse/blink animations; status remains readable.

## Phasing

1. **Phase 1 (MVP)**: Theater UI + log toggle; consume existing SSE; pipeline-activity event bus; graph pulse + throttled refetch.
2. **Phase 2**: Backend `activity` events with structured graph/note payloads; per-episode cards.
3. **Phase 3**: Incremental graph rendering (append nodes/edges from activity payloads without full refetch); optional particle flow canvas between stage strip and graph.
4. **Phase 4**: Dashboard "workspace heartbeat" widget summarizing all active ingestions across memory spaces.

## Related Specifications

- [`composable-eval-harness.md`](composable-eval-harness.md) — pipeline stages the theater visualizes.
- [`specs/uiux.md`](../uiux.md) — document processing state machine (Uploaded → Processing → Ready).
- [`specs/techstack.md`](../techstack.md) — Sprint 5b job observability (Redis pub/sub + SSE).
