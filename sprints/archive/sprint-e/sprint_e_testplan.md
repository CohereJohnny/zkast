# Sprint E Test Plan — LLM Wiki Memory

## Automated

- [ ] Migration `0015_wiki_memory` applies and downgrades without error.
- [ ] `test_wiki_repo.py`: create wiki space, insert pages + sources, query by workspace and agent scope.
- [ ] `test_wiki_generation.py`: `run_wiki_generation_job` records stats and emits pipeline log lines when redis is present.
- [ ] `test_wiki_isolation.py`: agent-scoped wiki must only ingest notes from that agent.
- [ ] `pnpm exec tsc --noEmit` green in `apps/web`.

## Manual

- [ ] Sidebar shows `Wiki` between `Graph` and `Chat`.
- [ ] Open `/wiki` on a fresh workspace; empty state offers "Generate wiki".
- [ ] Click Generate; status card shows running; pipeline log streams events (start, notes loaded, candidates, per-page progress, citations, completion).
- [ ] Wiki page list populates with `source_summary`, `entity`, `topic`, `synthesis`, `index`, `changelog` entries.
- [ ] Opening a page shows body, links, and a citation sidebar resolving to real notes/episodes/documents/conversations.
- [ ] Generate an agent-scoped wiki — citations only reference that agent's sources.
- [ ] Failed run shows failure reason + recovery guidance.
