"""Async HTTP client for North Agents & Conversations API."""

from __future__ import annotations

from collections import deque
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx


class NorthAuthError(Exception):
    """North rejected credentials (401 or redirect to a login page)."""


def _normalize_north_base_url(url: str) -> str:
    """Ensure known hosts use the correct API prefix.

    Cohere North demo serves REST under ``/api``; a bare origin plus httpx path ``/v1/...`` would
    otherwise hit ``/v1/...`` at the host root and get bounced to login.
    """
    raw = (url or "").strip()
    if not raw:
        return raw
    parsed = urlparse(raw.rstrip("/"))
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return raw.rstrip("/")
    host = parsed.netloc.lower()
    path = parsed.path or ""
    if host == "demo.north.cohere.com" and path in ("", "/"):
        return urlunparse((parsed.scheme, parsed.netloc, "/api", "", "", ""))
    return raw.rstrip("/")


def _north_api_url(base: str, *path_segments: str) -> str:
    """Join base (no trailing slash) and path segments without dropping path prefixes like ``/api``."""
    root = base.strip().rstrip("/")
    rel = "/".join(s.strip("/") for s in path_segments if s)
    return f"{root}/{rel}" if rel else root


def _unwrap_list(payload: Any, *, _depth: int = 0, _max_depth: int = 8) -> list[dict[str, Any]]:
    """Extract a list of dict rows from typical North / Cohere REST envelopes.

    OpenAPI often documents a bare array, but some deployments wrap rows or nest
    ``items`` one level down. We prefer stable keys first, then shallow recursion.
    """
    if _depth > _max_depth:
        return []
    if payload is None:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []

    priority_keys = (
        "agents",
        "data",
        "items",
        "results",
        "conversations",
        "chats",
        "threads",
        "records",
        "rows",
        "values",
        "agent_list",
    )
    for key in priority_keys:
        block = payload.get(key)
        if isinstance(block, list):
            rows = [x for x in block if isinstance(x, dict)]
            if rows:
                return rows
        if isinstance(block, dict):
            rows = _unwrap_list(block, _depth=_depth + 1, _max_depth=_max_depth)
            if rows:
                return rows

    for _key, block in payload.items():
        if isinstance(block, list):
            rows = [x for x in block if isinstance(x, dict)]
            if rows:
                return rows
        if isinstance(block, dict):
            rows = _unwrap_list(block, _depth=_depth + 1, _max_depth=_max_depth)
            if rows:
                return rows

    if (
        payload.get("id") is not None
        or payload.get("agent_id") is not None
        or payload.get("agentId") is not None
    ):
        return [payload]
    return []


# Prefer stable North identifiers before generic ``id`` (nested objects may also expose ``id``).
_NORTH_AGENT_ID_KEYS: tuple[str, ...] = (
    "agentId",
    "agent_id",
    "northAgentId",
    "north_agent_id",
    "uuid",
    "external_id",
    "externalId",
    "resource_id",
    "resourceId",
    "public_id",
    "publicId",
    "pk",
    "uid",
    "id",
)
_NORTH_AGENT_NAME_KEYS: tuple[str, ...] = (
    "displayName",
    "display_name",
    "name",
    "title",
    "label",
    "shortName",
    "short_name",
    "nickname",
)
# Do not descend into large / unrelated subtrees when scanning a list-agents row.
_SKIP_NORTH_AGENT_NEST_KEYS: frozenset[str] = frozenset(
    {
        "tools",
        "tool_definitions",
        "tool_calls",
        "tool_schemas",
        "messages",
        "history",
        "conversation_history",
        "documents",
        "runs",
        "events",
        "inputs",
        "outputs",
        "embeddings",
        "vectors",
        "chunks",
        "permissions",
        "acl",
        "policies",
        "stack_trace",
        "trace",
    }
)

# Descend into short lists of dicts under these keys (North sometimes nests the agent record).
_LIST_VALUE_CHILD_KEYS: frozenset[str] = frozenset(
    {
        "items",
        "results",
        "agents",
        "versions",
        "history",
        "entries",
        "records",
        "elements",
        "rows",
        "values",
        "payloads",
        "data",
    }
)


def _north_bfs_dict_nodes(root: dict[str, Any], *, max_nodes: int = 160) -> list[dict[str, Any]]:
    """Breadth-first dict nodes under ``root`` for key scans (bounded).

    Also steps into small dict-lists under common envelope keys so ids nested in
    ``items`` / ``versions`` / ``data`` are visible.
    """
    out: list[dict[str, Any]] = []
    q: deque[dict[str, Any]] = deque([root])
    seen: set[int] = set()
    while q and len(out) < max_nodes:
        d = q.popleft()
        i = id(d)
        if i in seen:
            continue
        seen.add(i)
        out.append(d)
        for k, v in d.items():
            if k in _SKIP_NORTH_AGENT_NEST_KEYS:
                continue
            if isinstance(v, dict):
                q.append(v)
            elif isinstance(v, list) and k in _LIST_VALUE_CHILD_KEYS:
                for el in v[:48]:
                    if isinstance(el, dict):
                        q.append(el)
    return out


def north_list_agent_external_id(item: dict[str, Any]) -> str:
    """Stable external id for upserting ``north_agents.external_agent_id``.

    North sometimes nests the agent under ``agent`` / ``metadata`` / ``spec`` or uses camelCase
    field names only present on inner objects.
    """
    for d in _north_bfs_dict_nodes(item):
        for key in _NORTH_AGENT_ID_KEYS:
            val = d.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    return ""


def north_list_agent_display_name(item: dict[str, Any], *, external_id: str) -> str:
    for d in _north_bfs_dict_nodes(item):
        for key in _NORTH_AGENT_NAME_KEYS:
            val = d.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()[:500]
    return external_id[:500]


def north_agent_id_for_api(external_agent_id: str) -> str:
    """North HTTP filters expect the bare agent id, not ``north:<uuid>`` style prefixes from some listings."""
    s = (external_agent_id or "").strip()
    while s:
        low = s.lower()
        stripped = False
        for prefix in ("north:", "cohere:"):
            if low.startswith(prefix):
                rest = s.split(":", 1)[1].strip()
                if rest:
                    s = rest
                    stripped = True
                    break
        if not stripped:
            break
    return s


def north_conversation_row_embedded_agent_external_id(row: dict[str, Any]) -> str | None:
    """When North includes an owning agent on a conversation list row, return that external id."""
    direct = row.get("agent_id") or row.get("agentId")
    if direct is not None and str(direct).strip():
        return str(direct).strip()
    agent = row.get("agent")
    if isinstance(agent, dict):
        for key in ("agentId", "agent_id", "id"):
            val = agent.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    meta = row.get("metadata")
    if isinstance(meta, dict):
        val = meta.get("agent_id") or meta.get("agentId")
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def north_conversation_row_matches_expected_agent(row: dict[str, Any], expected_agent_api_id: str) -> bool:
    """Skip rows whose embedded agent disagrees with the requested agent (North sometimes ignores filters)."""
    emb = north_conversation_row_embedded_agent_external_id(row)
    if emb is None:
        return True
    return north_agent_id_for_api(emb) == north_agent_id_for_api(expected_agent_api_id)


def json_safe(value: Any) -> Any:
    """Recursively convert values for ``JSONResponse`` / stdlib JSON (datetime, UUID, Decimal, …)."""
    import datetime as datetime_mod
    import uuid as uuid_mod
    from decimal import Decimal

    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, (datetime_mod.datetime, datetime_mod.date)):
        return value.isoformat()
    if isinstance(value, uuid_mod.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, memoryview)):
        return None
    return value


def _north_conversation_next_raw(body: dict[str, Any]) -> Any:
    for key in (
        "next_cursor",
        "nextCursor",
        "cursor",
        "nextPageToken",
        "next_page_token",
        "page_token",
        "continuation_token",
    ):
        v = body.get(key)
        if v is not None:
            return v
    return None


def _conversation_items_from_north_body(body: Any) -> list[dict[str, Any]]:
    """North may return a bare array, or an envelope dict; normalize to a list of dict rows."""
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if isinstance(body, dict):
        return _unwrap_list(body)
    return []


def _raise_for_north_response(response: httpx.Response) -> None:
    """Do not follow redirects: a 3xx to ``/login`` means the bearer token is wrong or missing."""
    if response.status_code in (301, 302, 303, 307, 308):
        location = (response.headers.get("location") or "").lower()
        if "login" in location:
            raise NorthAuthError(
                "North redirected to login — the bearer token is not accepted for this base URL. "
                "Use a North API token issued for this environment (e.g. demo.north.cohere.com), paste "
                "it under Rotate North bearer token, and try Test North again. A regular Cohere API key "
                "is not the same as a North token."
            ) from None
        response.raise_for_status()
    if response.status_code == 401:
        raise NorthAuthError(
            "North returned 401 Unauthorized — check that the stored bearer token is valid and not expired."
        ) from None
    if response.status_code == 403:
        raise NorthAuthError(
            "North returned 403 Forbidden — this token may lack permission to list agents or conversations."
        ) from None
    response.raise_for_status()


class NorthClient:
    def __init__(self, *, base_url: str, bearer_token: str) -> None:
        self._base = _normalize_north_base_url(base_url)
        self._headers = {"Authorization": f"Bearer {bearer_token.strip()}"}

    async def list_agents(self) -> list[dict[str, Any]]:
        """List agents from North, tolerating deployment differences in query validation.

        Cohere North demo rejects ``limit`` above the API maximum (often 100); we used 200 before,
        which still 422s after dropping ``visibility``. We try a small ladder of param sets, then
        paginate with ``offset`` when a page fills ``limit``.
        """
        url = _north_api_url(self._base, "v1", "agents")
        # Order: prefer visibility when supported; keep limit at or below typical API max (100).
        param_trials: tuple[dict[str, Any], ...] = (
            {"limit": 100, "offset": 0, "visibility": "ALL"},
            {"limit": 100, "offset": 0},
            {"limit": 50, "offset": 0},
            {},
        )
        async with httpx.AsyncClient(timeout=60.0) as client:
            working: dict[str, Any] | None = None
            last: httpx.Response | None = None
            for params in param_trials:
                r = await client.get(url, headers=self._headers, params=params, follow_redirects=False)
                last = r
                if r.status_code in (400, 422):
                    continue
                _raise_for_north_response(r)
                working = dict(params)
                break
            if working is None:
                assert last is not None
                _raise_for_north_response(last)

            assert last is not None
            accumulated = _unwrap_list(last.json())
            limit_val = working.get("limit") if working else None
            if isinstance(limit_val, int) and limit_val > 0:
                while len(accumulated) >= limit_val:
                    offset = len(accumulated)
                    next_params = {**working, "offset": offset}
                    r2 = await client.get(
                        url, headers=self._headers, params=next_params, follow_redirects=False
                    )
                    _raise_for_north_response(r2)
                    chunk = _unwrap_list(r2.json())
                    if not chunk:
                        break
                    accumulated.extend(chunk)
                    if len(chunk) < limit_val:
                        break
            return accumulated

    async def list_conversations(
        self,
        *,
        agent_id: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        url = _north_api_url(self._base, "v1", "conversations")

        async def _one_get(*, use_camel_agent: bool) -> httpx.Response:
            params: dict[str, Any] = {"limit": limit}
            if agent_id:
                if use_camel_agent:
                    params["agentId"] = agent_id
                else:
                    params["agent_id"] = agent_id
            if cursor:
                params["cursor"] = cursor
            async with httpx.AsyncClient(timeout=60.0) as client:
                return await client.get(url, headers=self._headers, params=params, follow_redirects=False)

        r = await _one_get(use_camel_agent=False)
        _raise_for_north_response(r)
        body = r.json()
        items = _conversation_items_from_north_body(body)
        raw_body: Any = body
        if not items and agent_id:
            r2 = await _one_get(use_camel_agent=True)
            _raise_for_north_response(r2)
            body2 = r2.json()
            items2 = _conversation_items_from_north_body(body2)
            if items2:
                items = items2
                raw_body = body2

        next_cursor: Any = None
        if isinstance(raw_body, dict):
            next_raw = _north_conversation_next_raw(raw_body)
            next_cursor = next_raw
            if isinstance(next_cursor, dict):
                next_cursor = next_cursor.get("cursor") or next_cursor.get("token")
        return {"items": items, "next_cursor": next_cursor, "raw": raw_body}

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        url = _north_api_url(self._base, "v1", "conversations", conversation_id)
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.get(url, headers=self._headers, follow_redirects=False)
            _raise_for_north_response(r)
            data = r.json()
            return data if isinstance(data, dict) else {"messages": [], "raw": data}
