"""Async HTTP client for the Slack Web API + OAuth v2 token exchange.

Mirrors the role of ``north_client.py`` for the Slack source. Covers the
read-only surface needed to register channels and import threads:

- OAuth v2 authorize URL + code→token exchange (``oauth.v2.access``)
- ``auth.test`` (verify a stored token, get team id/name)
- ``conversations.list`` (channels visible to the app)
- ``conversations.history`` (root messages in a channel)
- ``conversations.replies`` (a thread: root + replies)

Slack returns ``{"ok": false, "error": "..."}`` with HTTP 200 on logical
failures, so every call inspects the ``ok`` flag. ``ratelimited`` responses
(HTTP 429) carry a ``Retry-After`` header which we honour with bounded retries.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlencode

import httpx

SLACK_API_BASE = "https://slack.com/api"
SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"

# Minimum scopes to list channels and read history/threads.
DEFAULT_SLACK_BOT_SCOPES: tuple[str, ...] = (
    "channels:read",
    "channels:history",
    "groups:read",
    "groups:history",
)

_MAX_RATELIMIT_RETRIES = 3
_DEFAULT_RETRY_AFTER_S = 2.0


class SlackAuthError(Exception):
    """Slack rejected the token or OAuth exchange (invalid_auth, missing scope)."""


class SlackApiError(Exception):
    """A Slack Web API call returned ``ok: false`` for a non-auth reason."""


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: tuple[str, ...] = DEFAULT_SLACK_BOT_SCOPES,
) -> str:
    """Slack OAuth v2 consent URL the operator is redirected to."""
    query = urlencode(
        {
            "client_id": client_id,
            "scope": ",".join(scopes),
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{SLACK_AUTHORIZE_URL}?{query}"


def _raise_for_slack_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("ok"):
        return payload
    err = str(payload.get("error") or "unknown_error")
    auth_errors = {
        "invalid_auth",
        "not_authed",
        "account_inactive",
        "token_revoked",
        "token_expired",
        "missing_scope",
        "no_permission",
    }
    if err in auth_errors:
        raise SlackAuthError(f"Slack auth error: {err}")
    raise SlackApiError(f"Slack API error: {err}")


async def exchange_oauth_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Exchange an OAuth authorization code for an access token.

    Returns the raw ``oauth.v2.access`` payload, which includes
    ``access_token``, ``scope``, ``team.id`` / ``team.name``, and the
    token type. Caller persists the token encrypted.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{SLACK_API_BASE}/oauth.v2.access",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        return _raise_for_slack_payload(resp.json())


class SlackClient:
    def __init__(self, *, bot_token: str) -> None:
        self._headers = {"Authorization": f"Bearer {bot_token.strip()}"}

    async def _get(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{SLACK_API_BASE}/{method}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(_MAX_RATELIMIT_RETRIES + 1):
                resp = await client.get(url, headers=self._headers, params=params or {})
                if resp.status_code == 429 and attempt < _MAX_RATELIMIT_RETRIES:
                    retry_after = float(
                        resp.headers.get("Retry-After") or _DEFAULT_RETRY_AFTER_S
                    )
                    await asyncio.sleep(retry_after)
                    continue
                resp.raise_for_status()
                return _raise_for_slack_payload(resp.json())
        raise SlackApiError("Slack API rate limit exceeded after retries")

    async def auth_test(self) -> dict[str, Any]:
        """Verify the token; returns ``team_id``, ``team``, ``user_id``, etc."""
        return await self._get("auth.test")

    async def list_channels(
        self,
        *,
        types: str = "public_channel,private_channel",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """All channels the app can see, following cursor pagination."""
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "types": types,
                "limit": limit,
                "exclude_archived": "true",
            }
            if cursor:
                params["cursor"] = cursor
            body = await self._get("conversations.list", params)
            out.extend([c for c in (body.get("channels") or []) if isinstance(c, dict)])
            cursor = (body.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
        return out

    async def channel_history(
        self,
        *,
        channel_id: str,
        oldest: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Root messages in a channel (cursor-paginated, newest first)."""
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"channel": channel_id, "limit": limit}
            if oldest:
                params["oldest"] = oldest
            if cursor:
                params["cursor"] = cursor
            body = await self._get("conversations.history", params)
            out.extend([m for m in (body.get("messages") or []) if isinstance(m, dict)])
            cursor = (body.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
        return out

    async def thread_replies(
        self,
        *,
        channel_id: str,
        thread_ts: str,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Full thread (root + replies) for a root message timestamp."""
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "channel": channel_id,
                "ts": thread_ts,
                "limit": limit,
            }
            if cursor:
                params["cursor"] = cursor
            body = await self._get("conversations.replies", params)
            out.extend([m for m in (body.get("messages") or []) if isinstance(m, dict)])
            cursor = (body.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
        return out
