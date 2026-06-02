# Sprint Slack — Test Plan

Validates the spec-first deliverables: migration reversibility and the backend
skeleton's connect → list → register → threads surface. Import (501) and UI are
out of scope this sprint.

## 1. Migration (`0018_slack_source`)

| ID | Test | Expected |
|----|------|----------|
| M-1 | `alembic upgrade head` on a DB at `0017` | Applies cleanly; `memory_sources` view, `slack_connections`, `slack_conversation_cache` exist |
| M-2 | Insert a `documents` row with `source_kind='slack_conversation'`, `agent_id` NULL | Rejected by `ck_documents_slack_requires_agent` |
| M-3 | Insert `documents` `source_kind='slack_conversation'`, `mime_type='application/json'`, valid `agent_id` | Accepted |
| M-4 | Insert `episodes` `kind='slack_turn_window'` | Accepted |
| M-5 | Insert two `api_keys` rows `kind='slack_oauth'` for one workspace | Second rejected by `uq_api_keys_workspace_slack_oauth` |
| M-6 | `SELECT * FROM memory_sources` after creating a `north_agents` row with `provider='slack'` | Row visible with `external_id` aliased |
| M-7 | `alembic downgrade -1` | Reverses all objects; existing PDF/North rows intact |
| M-8 | Existing North import still works after upgrade | North ingestion unaffected (regression) |

## 2. Slack Web API client (`slack_client.py`)

| ID | Test | Expected |
|----|------|----------|
| C-1 | `build_authorize_url` | Contains client_id, encoded redirect_uri, scopes, state |
| C-2 | `_raise_for_slack_payload` with `{"ok": false, "error": "invalid_auth"}` | Raises `SlackAuthError` |
| C-3 | `_raise_for_slack_payload` with `{"ok": false, "error": "channel_not_found"}` | Raises `SlackApiError` |
| C-4 | `list_channels` with mocked cursor pagination | Aggregates across pages until empty `next_cursor` |
| C-5 | HTTP 429 then 200 (mocked) | Honors `Retry-After`, then succeeds |

## 3. Slack repo (`slack_repo.py`)

| ID | Test | Expected |
|----|------|----------|
| R-1 | `store_slack_oauth_token` then `fetch_slack_oauth_secret_row` | Round-trips encrypted secret; single row enforced |
| R-2 | `upsert_slack_connection` twice | Second call updates team name/scopes, no duplicate |
| R-3 | `upsert_slack_conversation_cache` same `(source_id, external_conversation_id)` | Updates payload + `fetched_at`, no duplicate |
| R-4 | `delete_slack_connection` + `delete_slack_oauth_token` | Removes connection + token |

## 4. Internal API (`internal_slack.py`)

| ID | Test | Expected |
|----|------|----------|
| A-1 | `GET .../slack/connection` (no token) | `{connected: false}` |
| A-2 | `POST .../slack/oauth/start` without Slack app env | 400 `slack_app_not_configured` |
| A-3 | `POST .../slack/oauth/start` with env set | Returns `authorize_url` + `state` prefixed by workspace id |
| A-4 | `POST .../slack/oauth/callback` with mismatched `state` | 400 `state_mismatch` |
| A-5 | `POST .../slack/oauth/callback` happy path (mocked exchange) | Stores token, upserts connection, `{connected: true}` |
| A-6 | `GET .../slack/channels` (no token) | 400 `slack_not_connected` |
| A-7 | `POST .../slack/channels/register` without `channel_id` | 400 `missing_channel_id` |
| A-8 | `POST .../slack/channels/register` | Creates memory source `provider='slack'`; appears registered in channel list |
| A-9 | `GET .../slack/channels/{source_id}/threads?refresh=true` (mocked history) | Caches threads; returns items with `external_conversation_id` |
| A-10 | `POST .../slack/channels/{source_id}/import` | 501 `slack_import_not_implemented` |

## 5. Manual smoke (requires a real Slack app)

1. Configure `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` / `SLACK_REDIRECT_URI` on the pipeline.
2. Hit OAuth start → approve in Slack → POST callback with the returned code.
3. List channels → register one → list threads (refresh) → confirm cache rows.

## Exit criteria

- M-1..M-8 pass (migration reversible, constraints enforced, North unaffected).
- C/R/A unit + route tests pass with mocked Slack HTTP.
- Import endpoint returns 501 by design; no Slack documents created this sprint.
