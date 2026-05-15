"""Async HTTP client for North Agents & Conversations API."""

from __future__ import annotations

from typing import Any

import httpx


def _unwrap_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "agents", "conversations", "results"):
        block = payload.get(key)
        if isinstance(block, list):
            return [x for x in block if isinstance(x, dict)]
    if payload.get("id"):
        return [payload]
    return []


class NorthClient:
    def __init__(self, *, base_url: str, bearer_token: str) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {bearer_token}"}

    async def list_agents(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(base_url=self._base, timeout=60.0) as client:
            r = await client.get("/v1/agents", headers=self._headers)
            r.raise_for_status()
            return _unwrap_list(r.json())

    async def list_conversations(
        self,
        *,
        agent_id: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if agent_id:
            params["agent_id"] = agent_id
        if cursor:
            params["cursor"] = cursor
        async with httpx.AsyncClient(base_url=self._base, timeout=60.0) as client:
            r = await client.get("/v1/conversations", headers=self._headers, params=params)
            r.raise_for_status()
            body = r.json()
            if not isinstance(body, dict):
                return {"items": [], "next_cursor": None, "raw": body}
            items = _unwrap_list(body)
            next_cursor = body.get("next_cursor") or body.get("cursor")
            if isinstance(next_cursor, dict):
                next_cursor = next_cursor.get("cursor")
            return {"items": items, "next_cursor": next_cursor, "raw": body}

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self._base, timeout=120.0) as client:
            r = await client.get(f"/v1/conversations/{conversation_id}", headers=self._headers)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else {"messages": [], "raw": data}
