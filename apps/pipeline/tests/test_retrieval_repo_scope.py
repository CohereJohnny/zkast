"""Retrieval record scope snapshot prefix."""

from __future__ import annotations

from app.retrieval_repo import _items_with_scope


def test_items_with_scope_adds_snapshot_when_agent_set() -> None:
    items = [{"id": "hit-1"}]
    out = _items_with_scope(items, {"agent_id": "a1"})
    assert out[0]["kind"] == "scope_snapshot"
    assert out[0]["scope"]["agent_id"] == "a1"
    assert out[1] == items[0]


def test_items_without_scope_unchanged() -> None:
    items = [{"id": "hit-1"}]
    assert _items_with_scope(items, {}) == items
    assert _items_with_scope(items, None) == items
