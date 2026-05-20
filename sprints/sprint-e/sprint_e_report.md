# Sprint E report

**Status**: Complete — merged to `main`.
**Branch**: `sprints/sprint-e`
**Spec**: [`specs/openspecs/llm-wiki-memory.md`](../../specs/openspecs/llm-wiki-memory.md)

## Shipped

| Area | Summary |
| ---- | ------- |
| **Spec** | New OpenSpec `llm-wiki-memory.md` defines requirements, data model, business rules, flows, UI, telemetry, edge cases, ACs, and non-normative framework candidates. |
| **Data model** | Migration `0015_wiki_memory` adds `wiki_spaces`, `wiki_pages`, `wiki_page_sources`, `wiki_generation_jobs`, `wiki_mutations`, `wiki_links` with enum checks, indexes, and scope uniqueness. |
| **Pipeline repo** | `apps/pipeline/app/wiki_repo.py` covers space/page/source/job/mutation/link CRUD plus an atomic-note loader that filters by agent scope. |
| **Worker** | `apps/pipeline/app/wiki_generation.py` ships a deterministic synthesizer that clusters notes by tag and source bucket, writes synthesis/topic/source-summary/index/changelog pages, attaches citations, records audit mutations, and emits verbose `record_log` / `publish_job_event` / `record_metric` telemetry under `stage=wiki_generation`. Registered as an arq task with a 20-minute timeout. |
| **Internal API** | `apps/pipeline/app/internal_wiki.py` exposes list/upsert/get-space, get-page, generate (`POST .../generate`), and get-job endpoints. Wired into FastAPI in `main.py`. |
| **Web proxies** | New `/api/v1/workspaces/[workspaceId]/wiki-spaces[...]` and `/wiki-jobs/[jobId]` routes proxy the internal API. |
| **UI** | New left-rail item `Wiki` (BookOpen icon) between `Graph` and `Chat`. `/wiki` route renders `WikiPanel` with scope selector + AgentPicker, generate button, `WikiJobStatus` card, two-column page list / reader, and a citation sidebar. The shared `JobLogConsole` docks at the bottom of `/wiki/*` and labels wiki events as `Wiki`. |
| **Telemetry** | `wiki_generation` registered as an `ActiveJobKind`; pipeline log stage label added; generation emits start, candidate counts, per-page upsert lines, metrics, and a completion summary. |
| **Tests** | `tests/test_wiki_generation.py` covers: no-notes success, full path with citations and mutations, agent scope isolation, verbose telemetry when redis is present, and unrecoverable failure marking. |

## Definition of done

- [x] Migration applies and matches the spec data model
- [x] Wiki nav item appears between Graph and Chat
- [x] Generate flow creates a wiki space (workspace or agent scope), queues a job, and shows live telemetry in the docked pipeline log
- [x] Generated pages carry citations to atomic notes (and an `agent` source row when agent-scoped)
- [x] No source artifact is mutated by wiki generation
- [x] `pnpm exec tsc --noEmit` clean; new pytest module passes (5/5); broader sprint test suite still green (25 passed, 4 skipped)

## Deferred (per spec, out of MVP scope)

- Chat / hybrid retrieval that reads wiki pages
- Full lint pass with cross-page contradiction detection
- Markdown / Obsidian export
- Document- and conversation-scoped wiki spaces (model supports them; UI is workspace + agent only)
- LLM-driven page bodies (current MVP uses deterministic, citation-grounded synthesis; the worker’s `_compose_*` helpers are the swap point)

## Next

Wiki MVP is shippable end-to-end. Logical next sprint: lint + chat retrieval integration so the wiki becomes a live memory source for graph/hybrid answers.
