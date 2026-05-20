# North history eval dataset (`north_history_v1.yaml`)

## Purpose

Exercise agent-scoped retrieval across `raw_transcript`, `zettelkasten_notes`,
`amem_lite`, `graph`, and `hybrid` modes (see `NORTH_HISTORY_MODES` in
`eval/runner.py`).

## Workspace seed (manual)

1. Configure North credentials and sync agents.
2. Import at least one conversation for the target agent.
3. Run A-MEM enrichment (Sprint B) so notes have `memory_context` /
   `memory_keywords`.
4. Backfill indexes for that agent:
   - `POST .../retrieval-index/backfill` with
     `kinds: ["raw_chunk", "note_zettel", "note_amem"]` and `agent_id`.
5. Optional: run **Dream** on the agent so `dreaming_touched_at` and link
   mutations exist for temporal questions.

## Local tests (link isolation)

Integration tests need a **real** Postgres URL, not a `...` placeholder:

```bash
export DATABASE_URL=postgresql://zkast:zkast@127.0.0.1:5432/zkast
cd apps/pipeline && python -m pytest tests/test_note_link_isolation.py -q
```

Ensure `docker compose up postgres` (or full stack) is running and migrations are applied through `0011`.

## Run

```bash
docker compose exec pipeline python -m app.eval.runner \
  --workspace-id <uuid> \
  --dataset north_history_v1 \
  --modes raw_transcript,zettelkasten_notes,amem_lite,graph,hybrid \
  --agent-id <north-agent-uuid>
```

Or via internal API: `POST .../eval/runs` with
`dataset_name: north_history_v1` and `agent_id` set.

Pattern scoring tolerates empty retrieval when the workspace lacks seeded
content; import real North transcripts for meaningful scores.
