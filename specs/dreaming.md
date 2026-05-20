# Dreaming Specification

## Overview

Dreaming is an offline memory-evolution process for an agent. It reviews the agent's existing atomic notes, identifies useful relationships between notes, records conservative derived-memory updates, refreshes retrieval memory for changed notes, and exposes enough status and telemetry for users to understand what is happening while the process runs.

Dreaming does not import new source content, regenerate notes from conversations, or rewrite canonical note content. It operates only on existing notes for the selected agent.

## Requirements

### Functional Requirements

- FR-1: A user can start a Dream run from an agent detail view.
- FR-2: A Dream run must be scoped to exactly one workspace and one agent.
- FR-3: The system must create a durable Dream job record when a run starts.
- FR-4: The system must process only notes that belong to the selected agent.
- FR-5: The system must identify candidate note relationships using semantic similarity between existing notes.
- FR-6: The system must evaluate whether candidate note relationships are strong enough to record.
- FR-7: The system must prefer no change when the relationship is weak or uncertain.
- FR-8: The system may create generated links between notes when a relationship is useful.
- FR-9: The system may update derived note memory fields, such as memory context and tags, when the update improves the target note's retrieval context.
- FR-10: The system must preserve canonical note title and body content during dreaming.
- FR-11: Every durable change made by a Dream run must be auditable as a Dream mutation.
- FR-12: Notes changed by dreaming must have retrieval memory refreshed so future agent chat and retrieval can use the evolved memory.
- FR-13: The Dream job must finish with a terminal status of succeeded or failed.
- FR-14: The Dream job must record summary statistics when it finishes.
- FR-15: The user interface must show the active Dream job status while the job runs.
- FR-16: The user interface must expose live pipeline telemetry for the running Dream job.
- FR-17: The user interface must show the count of recorded Dream mutations for the current or most recent Dream job.

### Non-Functional Requirements

- NFR-1: Dreaming must run asynchronously so the user interface remains responsive after the user starts a run.
- NFR-2: Dreaming must be bounded by configurable limits for notes considered, neighbors considered per note, and pair evaluations per run.
- NFR-3: Dreaming must not create cross-agent links or mutate notes from another agent.
- NFR-4: Dreaming telemetry must be live enough for users to distinguish active progress from a stuck run.
- NFR-5: Dreaming failures must be visible in both the job status and pipeline log.
- NFR-6: Dreaming must be safe to inspect after completion through stored job status, stats, and mutations.

## Data Model

### Dream Job

**Purpose**: Represents one asynchronous Dream run for one agent.

**Fields:**

- `id` (identifier, required): Unique Dream job identifier.
- `workspace_id` (identifier, required): Workspace that owns the run.
- `agent_id` (identifier, required): Agent whose notes are being processed.
- `status` (enum, required): Current job state. Allowed states are running, succeeded, and failed.
- `stats` (object, required): Summary counts and run metadata.
- `failure_reason` (text, nullable): Human-readable reason when the job fails.
- `started_at` (timestamp, required): Time the run was created.
- `ended_at` (timestamp, nullable): Time the run reached a terminal state.

**Constraints:**

- A Dream job belongs to exactly one workspace.
- A Dream job belongs to exactly one agent.
- A failed Dream job must include a failure reason.
- A terminal Dream job must include final stats.

### Dream Mutation

**Purpose**: Auditable record of each durable change made by a Dream run.

**Fields:**

- `id` (identifier, required): Unique mutation identifier.
- `dream_job_id` (identifier, required): Dream job that produced the mutation.
- `note_id` (identifier, required): Note affected by the mutation.
- `mutation_type` (enum, required): Type of mutation recorded.
- `payload` (object, required): Mutation-specific metadata.
- `created_at` (timestamp, required): Time the mutation was recorded.

**Mutation Types:**

- `link_added`: A generated relationship was recorded between notes.
- `neighbor_patch`: Derived memory fields were updated on a linked neighbor note.

**Constraints:**

- Each mutation must reference an existing Dream job.
- Each mutation must reference a note in the Dream job's agent scope.
- Mutation payloads must include enough information to understand what changed.

### Note Link

**Purpose**: Represents a generated relationship between two notes.

**Fields:**

- `source_note_id` (identifier, required): Source note for the relationship.
- `target_note_id` (identifier, required): Target note for the relationship.
- `kind` (enum, required): Relationship kind.
- `origin` (enum, required): Indicates the link was generated.
- `reason` (text, nullable): Explanation for why the relationship was created.
- `strength` (number, required): Relationship confidence or weight.

**Relationship Kinds:**

- `related`
- `supports`
- `extends`
- `refutes`
- `references`

**Constraints:**

- Source and target notes must belong to the same agent.
- Source and target notes must be different notes.
- Generated links must be auditable through a Dream mutation.

### Derived Note Memory

**Purpose**: Agent memory fields that can evolve without changing canonical note content.

**Fields:**

- `memory_context` (text, nullable): Derived context that helps retrieval and future reasoning.
- `tags` (list, nullable): Derived tags used for organization and retrieval.
- `dreaming_touched_at` (timestamp, nullable): Last time dreaming updated derived memory for the note.
- `evolution_history` (list, nullable): History of derived-memory changes.

**Constraints:**

- Dreaming may update derived note memory only for notes in the selected agent.
- Dreaming must not modify canonical note title or body.
- Any derived-memory update must be auditable.

## Business Rules

### Rule: Agent Scope Isolation

**Description**: A Dream run may only read and mutate notes for its selected agent.

**Applies To**: Note selection, candidate relationship discovery, link creation, derived-memory updates, and embedding refresh.

**Validation**: Every candidate note, link endpoint, mutation note, and refreshed retrieval record must belong to the Dream job's agent.

### Rule: Conservative Evolution

**Description**: Dreaming should create no change unless a useful relationship or derived-memory improvement is identified.

**Applies To**: Link creation and neighbor memory updates.

**Validation**: The system must allow a candidate evaluation to result in no mutation.

### Rule: Canonical Content Immutability

**Description**: Dreaming must not alter source-derived note title or body content.

**Applies To**: All note updates during a Dream run.

**Validation**: If a derived-memory update would change title or body content, the run must treat that as an immutability violation and must not count it as a successful neighbor update.

### Rule: Auditable Mutation

**Description**: Every durable change made by dreaming must be recorded as a Dream mutation.

**Applies To**: Generated links and derived-memory updates.

**Validation**: The mutation count shown in the user interface must correspond to persisted mutation records for the Dream job.

### Rule: Bounded Work

**Description**: Dreaming must respect configured limits so a run cannot grow without bound.

**Applies To**: Notes considered, neighbors considered per note, and pair evaluations per run.

**Validation**: The job stats and telemetry must indicate the amount of work performed and whether a configured cap stopped the run early.

## User Flows

### Flow: Start Dream Run

**Trigger**: User clicks Dream on an agent detail view.

**Preconditions:**

- User has access to the workspace.
- The selected agent exists.
- The selected agent has existing notes.
- Required model credentials are available.

**Steps:**

1. User clicks Dream.
2. System creates a Dream job for the selected agent.
3. System queues asynchronous work.
4. System returns a job identifier to the user interface.
5. User interface shows the Dream job as running.
6. User interface opens or exposes the pipeline log panel for live telemetry.

**Success Outcome:**

- A Dream job is visible with running status.
- Pipeline log is subscribed to the job.
- The user can watch progress without leaving the agent detail view.

**Error Outcomes:**

- Agent not found: Show a not-found error.
- Missing credentials: Mark the job failed and show a failure reason.
- Queue failure: Show an actionable error and do not present the job as running.

### Flow: Process Existing Agent Memory

**Trigger**: A queued Dream job starts in the worker.

**Steps:**

1. System loads Dream configuration for the workspace.
2. System loads a bounded set of notes for the selected agent.
3. If fewer than two notes are available, system completes successfully with a not-enough-notes message.
4. System computes semantic representations for the selected notes.
5. For each focus note, system identifies the most similar neighbor notes.
6. System evaluates whether the focus note should be linked to a neighbor.
7. If a useful link is identified, system records the generated note link and mutation.
8. If a derived-memory update is identified, system updates allowed derived fields and records a mutation.
9. System refreshes retrieval memory for touched notes.
10. System finalizes the job with status and summary stats.

**Success Outcome:**

- The job is marked succeeded.
- Generated links and derived-memory updates are persisted.
- Mutations and stats are available for inspection.
- Touched notes have refreshed retrieval memory.

**Error Outcomes:**

- Model or embedding failure: Mark job failed with failure reason.
- Unexpected processing failure: Mark job failed with failure reason.
- Invalid candidate output: Skip the invalid candidate and continue when possible.

### Flow: Watch Dream Telemetry

**Trigger**: A Dream job is running and the pipeline log panel is open.

**Steps:**

1. User interface subscribes to the Dream job event stream.
2. System emits a start log.
3. System emits note-loading and embedding logs.
4. System emits periodic progress while notes are evaluated.
5. System emits link and neighbor-patch logs when mutations occur.
6. System emits embedding-refresh logs when retrieval memory is refreshed.
7. System emits completion or failure logs.

**Success Outcome:**

- User can tell which phase the job is in.
- User can see progress counts and mutation-producing actions.
- User can distinguish active work from a stalled or failed job.

**Error Outcomes:**

- Stream disconnects: User interface may stop receiving live updates but job status remains recoverable from stored job data.
- Job fails: Pipeline log and status card show the failure.

## Telemetry Requirements

### Job Status

The Dream job status view must show:

- Job identifier.
- Current status.
- Mutation count.
- Failure reason when present.
- Final summary stats when complete.

### Pipeline Log

The pipeline log should show:

- Dream job start.
- Number of notes loaded.
- Work limits for the run.
- Embedding phase completion.
- Periodic note-evaluation progress.
- Generated links as they are recorded.
- Neighbor patches as they are recorded.
- Retrieval-memory refresh.
- Completion or failure.

### Summary Stats

Final stats should include:

- `notes_considered`: Number of notes loaded for the run.
- `pairs_considered`: Number of candidate evaluations completed.
- `links_added`: Number of generated note links recorded.
- `neighbors_updated`: Number of notes with derived-memory updates.
- `embeddings_refreshed`: Number of notes with refreshed retrieval memory.
- `immutability_violations`: Number of attempted updates that would have changed canonical note content.
- `pairs_cap_reached`: Whether the run stopped because the pair-evaluation cap was reached.

## Authorization

### Permission: Run Dream

**Required Access**: User must be authorized for the workspace containing the agent.

**Resource-Level Checks:**

- Workspace must match the selected agent.
- Dream job must be created only for agents in the selected workspace.

**Enforcement:**

- User-facing endpoints must validate workspace access.
- Internal processing must validate agent and note scope.

## Validation Rules

### Field: Dream Job Status

- **Required**: Yes.
- **Allowed Values**: running, succeeded, failed.
- **Custom Rules**: A terminal job must not return to running.

### Field: Mutation Type

- **Required**: Yes.
- **Allowed Values**: link_added, neighbor_patch.
- **Custom Rules**: Mutation payload must match mutation type.

### Field: Note Link Kind

- **Required**: Yes.
- **Allowed Values**: related, supports, extends, refutes, references.
- **Custom Rules**: Unknown relationship kinds must not be persisted as-is.

### Field: Derived Tags

- **Required**: No.
- **Format**: Lowercase, trimmed text labels.
- **Custom Rules**: Duplicate tags should be collapsed.

## User Interface Requirements

### View: Agent Detail

**Purpose**: Lets the user inspect an agent's conversations and run offline memory evolution.

**Display Elements:**

- Dream action: Starts a Dream run for the selected agent.
- Dream status card: Shows current or recent Dream job state.
- Mutation count: Shows number of changes recorded for the Dream job.
- Pipeline log panel: Shows live Dream telemetry while the job runs.

**Actions Available:**

- Start Dream: Available when no local Dream action is currently being submitted.
- Show pipeline log: Available while a Dream job is running.

**States:**

- Idle: No current Dream job is running.
- Starting: User clicked Dream and the start request is in progress.
- Running: Dream job is active and telemetry is available.
- Succeeded: Dream job finished successfully with summary stats.
- Failed: Dream job failed with a visible failure reason.

### View: Pipeline Log

**Purpose**: Provides live insight into asynchronous Dream work.

**Display Elements:**

- Active job count.
- Job filter.
- Level filter.
- Follow toggle.
- Timestamped log lines.
- Stage label for Dream events.

**States:**

- Waiting: Job is active but no events have arrived yet.
- Streaming: Events are arriving and displayed.
- Completed: Terminal event has arrived.
- Empty: No active jobs are registered.

## Edge Cases

### Case: Not Enough Notes

**Scenario**: Agent has fewer than two notes.

**Expected Behavior**: Dream job succeeds with no mutations and records a not-enough-notes message.

**Error Handling**: This is not treated as a failure.

### Case: Weak Relationships

**Scenario**: Candidate notes do not have useful relationships.

**Expected Behavior**: System records no mutation for those candidates and continues.

**Error Handling**: This is normal behavior.

### Case: Invalid Candidate Output

**Scenario**: Relationship evaluation returns malformed or unusable output.

**Expected Behavior**: System logs a warning, skips the candidate, and continues when possible.

**Error Handling**: The job should not fail solely because one candidate output is invalid.

### Case: Cross-Agent Link Attempt

**Scenario**: A candidate relationship points outside the selected agent scope.

**Expected Behavior**: System rejects the link and continues.

**Error Handling**: The job should not persist the cross-agent relationship.

### Case: Canonical Content Mutation Attempt

**Scenario**: A derived-memory update would change note title or body content.

**Expected Behavior**: System detects the violation, does not count the update as successful, and records the violation in stats.

**Error Handling**: The job may continue if the violation is isolated.

### Case: Work Cap Reached

**Scenario**: Dreaming reaches a configured note or pair-evaluation cap before all notes are evaluated.

**Expected Behavior**: System stops additional evaluations, records that the cap was reached, and finalizes the job with partial stats.

**Error Handling**: This is not a failure.

### Case: Model Credentials Missing

**Scenario**: Required model credentials are unavailable.

**Expected Behavior**: Dream job fails with a visible failure reason.

**Error Handling**: User interface shows the failure in the status card and pipeline log.

### Case: Telemetry Stream Disconnects

**Scenario**: User interface loses the live event stream while a Dream job continues.

**Expected Behavior**: Stored job status and mutation count remain available through polling.

**Error Handling**: The user should be able to refresh or re-open the job view to recover current status.

## Acceptance Criteria

- [ ] AC-1: Clicking Dream on an agent creates a Dream job scoped to that workspace and agent.
- [ ] AC-2: The user interface shows the Dream job as running after the start request succeeds.
- [ ] AC-3: The pipeline log appears on the agent detail view while a Dream job is active.
- [ ] AC-4: The pipeline log shows live Dream telemetry beyond a single start message.
- [ ] AC-5: Dreaming never processes or mutates notes outside the selected agent.
- [ ] AC-6: Dreaming can complete successfully with zero mutations when no useful relationships are found.
- [ ] AC-7: Generated links are persisted with an auditable Dream mutation.
- [ ] AC-8: Derived-memory updates are persisted with an auditable Dream mutation.
- [ ] AC-9: Dreaming does not change note title or body content.
- [ ] AC-10: Touched notes have retrieval memory refreshed before the job is marked succeeded.
- [ ] AC-11: The Dream job status card shows mutation count while the job runs.
- [ ] AC-12: Completed Dream jobs show final stats for notes considered, pairs considered, links added, neighbors updated, and embeddings refreshed.
- [ ] AC-13: Failed Dream jobs show a failure reason in the user interface.

## Success Metrics

- Users can determine the current phase of a running Dream job from the pipeline log.
- Dream jobs produce auditable mutation records for every durable change.
- Dreaming improves agent memory connectivity without modifying canonical note content.
- Dream runs remain bounded and complete within configured limits.

## Related Specifications

- Agent conversation import: Provides the source conversations that produce notes for dreaming.
- Atomic notes: Provides the memory units dreaming links and enriches.
- A-MEM retrieval: Consumes refreshed embeddings and derived memory after dreaming.
- Pipeline jobs and telemetry: Provides asynchronous job status and live event visibility.
