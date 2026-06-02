# Sprint Slack — Tasks

Add **Slack** as a first-class ingestion source, generalizing the North agent
registry into a provider-neutral **memory source** concept.

- **Spec:** [`specs/openspecs/slack-source.md`](../../specs/openspecs/slack-source.md)
- **Branch:** `sprint-slack`
- **Decisions (locked):** generalize `north_agents` → memory sources · Slack **OAuth** · **channel = memory space, thread = document** · **spec-first** sprint (OpenSpec + migration + backend skeleton, no full UI).

## Goals

1. Author the OpenSpec describing the Slack source and the memory-sources generalization.
2. Land a reversible migration: `slack_conversation` source kind, slack episode kinds, Slack connection + cache tables, Slack OAuth credential kind, neutral `memory_sources` view.
3. Provide a backend skeleton (Slack Web API client, repo, internal router) covering connect → list channels → register channel → list/cache threads end to end.
4. Validate the design without building the full UI or wiring thread import (deferred to the implementation sprint).

## Tasks

### Phase 1 — Spec & design (this sprint)

- [x] Explore North source architecture end to end; identify Slack extension points.
- [x] Write `specs/openspecs/slack-source.md` (requirements, data model, flows, ACs) per the OpenSpec writing guide.
- [x] Confirm key decisions with stakeholder (agent model, auth, scope unit, sprint scope).

### Phase 2 — Migration scaffolding (this sprint)

- [x] `0018_slack_source.py`: add `provider_metadata` to registry; create `memory_sources` view.
- [x] Extend `documents.source_kind` → add `slack_conversation`; extend mime + add `ck_documents_slack_requires_agent`.
- [x] Add `documents.external_conversation_id` + `documents.source_metadata`; index.
- [x] Extend `episodes.kind` → add `slack_message`, `slack_turn_window`.
- [x] `slack_connections` table (team metadata; token in `api_keys`).
- [x] `slack_conversation_cache` table (thread payloads).
- [x] Partial unique index `uq_api_keys_workspace_slack_oauth`.
- [x] Reversible `downgrade()`.
- [ ] Run migration up/down against a scratch DB to confirm reversibility (manual — see test plan).

### Phase 3 — Backend skeleton (this sprint)

- [x] `slack_client.py`: OAuth authorize URL + code exchange; `auth.test`; `conversations.list/history/replies`; rate-limit retries.
- [x] `slack_repo.py`: encrypted OAuth token storage; `slack_connections` upsert/fetch/delete; thread cache.
- [x] `internal_slack.py`: connection status, OAuth start/callback, disconnect, list channels, register channel, list/cache threads.
- [x] Register router in `main.py`.
- [x] `config.py`: `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` / `SLACK_REDIRECT_URI`.
- [x] Import-check modules and router (8 routes).
- [ ] `import` endpoint returns 501 (intentional) until Phase 5.

### Phase 4 — Implementation sprint (deferred, NOT this sprint)

- [ ] Slack transcript → episode adapter (root + replies → `slack_turn_window` / `slack_message`), reusing `transcript_episodes.py` patterns.
- [ ] Ingest content-hash dedup (`slack_checksum.py` mirroring `north_checksum.py`).
- [ ] `tasks.parse_document` branch on `source_kind == 'slack_conversation'` → `_parse_slack_thread`.
- [ ] Import handler: create `slack_conversation` document + enqueue parse → notes → graph.
- [ ] Channel-scoped wiki generation reuse (`scope_kind='agent'` with the channel source id).
- [ ] Retrieval/chat source scope honored for Slack channels.

### Phase 5 — Web UI (deferred, NOT this sprint)

- [ ] Settings: Connect/Reconnect/Disconnect Slack (OAuth round trip + state handling).
- [ ] Channel browser + register.
- [ ] Channel detail: thread list, preview, import, generate wiki.
- [ ] BFF routes under `apps/web/src/app/api/v1/workspaces/[workspaceId]/slack/...` proxying to pipeline.

## Deviations / notes

- Physical rename of `north_agents` → `memory_sources` and `agent_id` → `source_id` is **deferred** (large, risky). This sprint introduces a read-side `memory_sources` view and widens column semantics only. Logged for a future refactor sprint.
- Slack thread import deliberately returns **501** in this sprint to avoid dangling document state.

## Sprint Review

- **Demo readiness:** Connect Slack (OAuth), list channels, register a channel, list+cache threads all functional via internal API once a Slack app + token exist.
- **Gaps:** No UI; thread import → notes/graph/wiki not yet wired; migration not yet run against a live DB.
- **Next steps:** Phase 4 implementation sprint (adapter + dedup + parse branch + import enqueue), then Phase 5 UI.
