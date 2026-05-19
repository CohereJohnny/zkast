"""North HTTP client auth / redirect handling."""

from __future__ import annotations

import httpx
import pytest

from app.north_client import (
    NorthAuthError,
    _normalize_north_base_url,
    _north_api_url,
    _raise_for_north_response,
    _unwrap_list,
    json_safe,
    north_agent_id_for_api,
    north_conversation_row_embedded_agent_external_id,
    north_conversation_row_matches_expected_agent,
    north_list_agent_display_name,
    north_list_agent_external_id,
)


def test_unwrap_root_json_array() -> None:
    assert _unwrap_list([{"id": "a", "name": "One"}, {"id": "b", "name": "Two"}]) == [
        {"id": "a", "name": "One"},
        {"id": "b", "name": "Two"},
    ]


def test_unwrap_nested_agents_items() -> None:
    payload = {"agents": {"items": [{"id": "x", "name": "Nested"}]}}
    assert _unwrap_list(payload) == [{"id": "x", "name": "Nested"}]


def test_unwrap_data_wrapped_list() -> None:
    assert _unwrap_list({"data": [{"id": "1"}]}) == [{"id": "1"}]


def test_unwrap_single_object_with_agent_id_only() -> None:
    assert _unwrap_list({"agentId": "only-camel"}) == [{"agentId": "only-camel"}]


def test_raise_for_north_response_redirect_to_login() -> None:
    req = httpx.Request("GET", "https://demo.north.cohere.com/v1/agents")
    resp = httpx.Response(307, request=req, headers={"location": "/login?redirect_uri=x"})
    with pytest.raises(NorthAuthError, match="North redirected to login"):
        _raise_for_north_response(resp)


def test_raise_for_north_response_401() -> None:
    req = httpx.Request("GET", "https://demo.north.cohere.com/v1/agents")
    resp = httpx.Response(401, request=req)
    with pytest.raises(NorthAuthError, match="401"):
        _raise_for_north_response(resp)


def test_normalize_demo_north_origin_adds_api_prefix() -> None:
    assert _normalize_north_base_url("https://demo.north.cohere.com") == "https://demo.north.cohere.com/api"
    assert _normalize_north_base_url("https://demo.north.cohere.com/") == "https://demo.north.cohere.com/api"


def test_normalize_demo_north_with_api_unchanged() -> None:
    assert _normalize_north_base_url("https://demo.north.cohere.com/api") == "https://demo.north.cohere.com/api"


def test_north_api_url_joins_under_api_prefix() -> None:
    assert _north_api_url("https://demo.north.cohere.com/api", "v1", "agents") == (
        "https://demo.north.cohere.com/api/v1/agents"
    )


def test_north_list_agent_external_id_snake_case() -> None:
    assert north_list_agent_external_id({"id": "ag-1", "name": "A"}) == "ag-1"


def test_north_list_agent_external_id_camel_case() -> None:
    assert north_list_agent_external_id({"agentId": "cohere-xyz", "displayName": "Demo"}) == "cohere-xyz"


def test_north_list_agent_external_id_nested_agent() -> None:
    assert north_list_agent_external_id({"agent": {"agentId": "nested-1"}}) == "nested-1"


def test_north_list_agent_external_id_deep_nested() -> None:
    assert north_list_agent_external_id({"wrapper": {"metadata": {"north_agent_id": "deep-9"}}}) == "deep-9"


def test_north_list_agent_external_id_under_items_list() -> None:
    row = {"items": [{"agentId": "from-nested-list"}]}
    assert north_list_agent_external_id(row) == "from-nested-list"


def test_north_agent_id_for_api_strips_prefix() -> None:
    assert north_agent_id_for_api("north:e0e326ef-3e17-40b0-8214-2fcf5ba72856") == "e0e326ef-3e17-40b0-8214-2fcf5ba72856"
    assert north_agent_id_for_api("plain-uuid") == "plain-uuid"


def test_north_agent_id_for_api_strips_double_prefix() -> None:
    assert north_agent_id_for_api("north:north:abc-123") == "abc-123"


def test_conversation_items_root_array() -> None:
    from app.north_client import _conversation_items_from_north_body

    rows = _conversation_items_from_north_body([{"id": "c1", "title": "T"}])
    assert rows == [{"id": "c1", "title": "T"}]


def test_north_conversation_row_matches_expected_agent() -> None:
    assert north_conversation_row_matches_expected_agent({"id": "c1"}, "any-agent")
    assert north_conversation_row_matches_expected_agent({"id": "c1", "agentId": "ag-1"}, "ag-1")
    assert north_conversation_row_matches_expected_agent({"id": "c1", "agent_id": "north:ag-1"}, "ag-1")
    assert not north_conversation_row_matches_expected_agent({"id": "c1", "agentId": "other"}, "ag-1")


def test_north_conversation_row_embedded_nested_agent() -> None:
    assert north_conversation_row_embedded_agent_external_id({"agent": {"agentId": "x"}}) == "x"


def test_json_safe_datetime() -> None:
    from datetime import datetime, timezone

    assert json_safe({"t": datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)})["t"].startswith("2024-01-02")


def test_north_list_agent_display_name_camel_case() -> None:
    assert north_list_agent_display_name({"agentId": "x", "displayName": "Hello"}, external_id="x") == "Hello"


def test_raise_for_north_response_ok() -> None:
    req = httpx.Request("GET", "https://demo.north.cohere.com/v1/agents")
    resp = httpx.Response(200, request=req, json={"agents": []})
    _raise_for_north_response(resp)
