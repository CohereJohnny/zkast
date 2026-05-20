# Sprint C report

**Status**: Complete — merged to `main`.
**Branch**: `sprints/sprint-c`
**Spec**: [north-agents-amem.md](../../specs/openspecs/north-agents-amem.md) (FR-6, FR-8, FR-9, FR-10); [dreaming.md](../../specs/dreaming.md)

## Shipped

| Area | Summary |
| ---- | ------- |
| **Dreaming jobs** | Agent-scoped offline evolution: embed notes, LLM pair decisions, generated links, derived `memory_context`/tags, A-MEM re-index, auditable `dream_job_mutations` |
| **Dreaming API** | `POST .../dream`, dream-jobs list/detail, pipeline caps, immutability guard |
| **Jobs UI** | Jobs page, Redis job overview, `DreamJobStatus`, pipeline log on conversations/jobs/agent detail |
| **Dream telemetry** | Progressive `record_log` / `stage_progress` during dreaming so pipeline log is actionable |
| **Link isolation** | Cross-agent link rejection tests; documented null-agent edge cases |
| **Retrieval scope** | Agent filter for `raw_transcript`, `zettelkasten_notes`, `amem_lite`; scope snapshot on retrieval records |
| **North import UX** | Ingest content hash dedup, sync status (`synced` / `outdated` / `syncing`), per-conversation memory telemetry |
| **A-MEM counts** | Fixed per-conversation and agent-level indexed counts (embeddings keyed by `source_id`) |
| **Chat** | Migration `0014` adds `amem_lite` retrieval mode; turn errors surface `failure_reason` |
| **Eval** | Expanded `north_history_v1` dataset, north-specific eval modes, README |
| **Tests** | Dreaming, link isolation, retrieval scope, north import status, eval modes |

## Definition of done

- [x] Dreaming runs per agent without mutating note `body`/`title`
- [x] Mutations auditable (`dream_jobs`, `dream_job_mutations`, `evolution_history`)
- [x] Retrieval/eval respect `agent_id` across supported modes
- [x] Cross-agent note links rejected when both agents are set
- [x] North-history eval dataset + modes; CLI/API `agent_id`
- [x] Pipeline + web tests / typecheck green for Sprint C scope

## Gaps / deferred

- Chat scope picker still manual UUID → TD-016 (Sprint D)
- No eval results UI (CLI/internal API only)
- Graph/hybrid agent isolation depends on ingest-time `agent_id` on documents

## Next

Sprint D — product polish, chat AgentPicker, spec sync ([sprint_d_tasks.md](../sprint-d/sprint_d_tasks.md)).
