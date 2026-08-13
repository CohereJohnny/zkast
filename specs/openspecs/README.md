# OpenSpecs index + specification reconciliation ledger

This directory holds **OpenSpec** documents — feature-scoped specifications that describe **WHAT** is built (technology-agnostic intent), per the OpenSpec writing guide. This README is the **index** of those specs and the **reconciliation ledger** that tracks where the implemented system has moved ahead of the core specs in [`specs/`](../).

## Spec maintenance convention (lightweight, per-change)

To keep drift bounded without heavyweight process:

1. Every sprint / PR that adds or changes behavior updates the **relevant OpenSpec** (or adds a new one here) at the WHAT level — not auto-generated from code.
2. The PR description includes a one-line **spec delta** (what intent changed) and updates the **Reconciliation ledger** below if it touches schema, APIs, or architecture not yet woven into the core specs.
3. Core specs ([`datamodel.md`](../datamodel.md), [`apis.md`](../apis.md), [`techstack.md`](../techstack.md)) remain authoritative for intent; when an OpenSpec's content is fully merged into a core spec, mark it "merged" here.

## OpenSpec inventory

- [`north-agents-amem.md`](north-agents-amem.md) — North agent ingestion, A-MEM memory enrichment, dreaming. Partially merged into `datamodel.md` (North section). Not reflecting `north_agents.provider_metadata` or the Slack-driven memory-source generalization.
- [`llm-wiki-memory.md`](llm-wiki-memory.md) — Wiki spaces / pages / generation jobs (migration `0015`). Not yet woven into `datamodel.md` or `apis.md`.
- [`slack-source.md`](slack-source.md) — Slack as an ingestion source + provider-neutral memory-source generalization (migration `0018`). Not yet woven into `datamodel.md` or `apis.md`.
- [`composable-eval-harness.md`](composable-eval-harness.md) — pluggable pipeline stages, Pipeline Configurations (versioned + content-hashed), versioned ontology/prompt sets (manual + auto-tune), Microsoft GraphRAG as the first new extractor+retrieval plugin, comparison/attribution, and the Pipelines/Lab surface. The forward-looking architecture for the harness; not yet implemented in code.
- [`live-ingestion-theater.md`](live-ingestion-theater.md) — MiroFish-inspired live observability: pipeline activity theater (stage LEDs, metric tiles, activity feed), graph pulse during extraction, SSE `activity` events. Phase 1 MVP in progress.

## Reconciliation ledger (shipped, not yet fully in core specs)

Last reconciled: migrations `0001`..`0018`. The core specs predate several shipped subsystems. The authoritative schema is the Alembic migrations under [`apps/migrations/alembic/versions/`](../../apps/migrations/alembic/versions/); the authoritative routes are `apps/pipeline/app/internal_*.py` + `apps/web/src/app/api/v1/**`. Until the core specs are rewritten inline, treat the items below as the current intent.

### datamodel.md — schema shipped but not (or wrongly) documented
- Slack / memory-source generalization (`0018`): `slack_connections`, `slack_conversation_cache`, the `memory_sources` VIEW over `north_agents`; `documents.external_conversation_id` + `documents.source_metadata`; `documents.source_kind` adds `slack_conversation`; `episodes.kind` adds `slack_message` / `slack_turn_window`; `north_agents.provider_metadata`; `api_keys.kind = slack_oauth` (partial unique index).
- Retrieval embeddings (`0010`/`0011`/`0012`): full `retrieval_embeddings` pgvector table; `index_kind` ∈ `raw_chunk`, `atomic_note`, `entity`, `relationship`, `graph_context`, `note_zettel`, `note_amem`; `agent_id` column.
- Eval harness (`0010`/`0014`/`0016`): `chat_eval_runs` / `chat_eval_questions` / `chat_eval_results`; results unique on `(run_id, question_id, retrieval_mode, top_k_cutoff)`; `eval_kind`, `agent_id`, `top_k_cutoffs`, `run_config`, `summary`, `memory_system`, `retrieval_items`, judge fields.
- Wiki (`0015`): `wiki_spaces`, `wiki_pages`, `wiki_page_sources`, `wiki_generation_jobs`, `wiki_mutations`, `wiki_links`.
- Usage accounting (`0017`): `usage_events` (`usage_source` ∈ chat|ingestion|wiki|dream|eval|retrieval|other; agent/document/job/run scope, tokens, model).
- Agent-scoped graph (`0017`): `agent_id` on `entities`, `relationships`, `graphiti_entity_map`, `graphiti_edge_map`; entity dedup is now partial-unique split by null vs non-null `agent_id` (global vs agent scope), replacing the flat `(workspace_id, type, canonical_name)` unique.
- Graphiti bridge tables (`0005`/`0017`): `graphiti_entity_map`, `graphiti_edge_map` (graphiti UUID → canonical id).
- Provenance is junction tables, not list fields: `note_episodes`, `entity_episodes`, `entity_notes`, `relationship_episodes`, `relationship_notes` (`0005`).
- Snapshots store frozen child rows: `snapshot_entities` / `snapshot_relationships` / `snapshot_notes` (`0006`), not opaque id sets.
- `chat_messages.retrieval_mode` (`0009`/`0014`): `graph`, `rag`, `hybrid`, `raw_transcript`, `zettelkasten_notes`, `amem_lite` (eval results also allow `wiki`).
- Ontology enum correction: shipped extractor types ([`entity_schemas.py`](../../apps/pipeline/app/entity_schemas.py)) are `Person`, `Organization`, `Concept`, `Location`, `Document`, `Standard`, `Equipment`, `Process`, `Material`, `Event` and edges `WORKS_FOR`, `PUBLISHED`, `MANAGES`, `INSPECTS`, `MITIGATES`, `RELATES_TO`, etc. — not the `Work`/`Date`/`AUTHORED_BY` set the spec lists. (Note: the composable-harness work will make this ontology a versioned, editable artifact rather than a hardcoded constant.)
- Spec-only / not migrated (aspirational): `custom_types`, `external_graph_targets`, `persistence_jobs`, `audit_log_entries`.

### apis.md — routes shipped but not documented (or stale)
- Slack: `/internal/v1/workspaces/{id}/slack/*` (connection, oauth/start, oauth/callback, connect-token, sources, channels, channels/register, channels/{sourceId}/threads, channels/{sourceId}/import).
- Dashboard: `GET .../dashboard`. Diagnostics / retrieval index: `GET .../retrieval-index/status`, `POST .../retrieval-index/backfill`. Jobs: `GET .../jobs/overview`, `GET .../documents/{id}/logs`.
- Wiki: `wiki-spaces` CRUD + `/generate` + `wiki-jobs/{id}`. Eval: `/eval/datasets`, `/eval/runs[/{id}]`. Reset: `/reset`, `/reset/preview`. North: `/north/agents/{id}/stats`, conversation `/preview`.
- Chat model correction (stale in apis.md): there is no `POST .../chat/turns` SSE endpoint. A turn is an arq job `run_chat_turn` on queue `arq:queue:chat`; the client streams via `GET /api/v1/workspaces/{id}/chat/turns/{turnId}` → `GET /internal/v1/jobs/{turnId}/events` (Redis Stream replay). `POST .../chat-sessions/{id}/messages` returns a `turn_id`. Not implemented: delete-session, regenerate, select-alternate, persistence-jobs (stub only).

### techstack.md — corrected inline in this reconciliation (see file)
- FalkorDB naming is now memory-space based ([`memory_space.py`](../../apps/pipeline/app/memory_space.py)): global graph = workspace UUID with hyphens→underscores; per-agent graph = `{ws}_a_{agent}` (RediSearch-safe). Supersedes the BUG-011 "database == workspace UUID verbatim" paragraph.
- Dedicated chat worker: `ChatWorkerSettings` + `arq:queue:chat` ([`queues.py`](../../apps/pipeline/app/queues.py)) + compose `chat-worker` service, isolating chat from bulk ingestion. Concurrency caps: `WORKER_MAX_JOBS=4`, `SEMAPHORE_LIMIT=4` (worker) / `6` (chat-worker).
- Additional arq jobs: `run_dreaming_job`, `run_wiki_generation_job`, `import_slack_channel`. Raw-chunk auto-indexing runs after parse (`_index_raw_chunk_embeddings`).
- LangExtract ships P0 on Cohere (the "Gemini required to unlock LangExtract" line is corrected).
- MS GraphRAG stance: still not the production ingestion engine, but now being added as a **parallel, opt-in comparison backend** within the composable-evaluation-harness initiative (see the active plan / forthcoming OpenSpec).
