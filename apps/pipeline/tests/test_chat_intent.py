"""Sprint 6b — intent router unit tests.

Pins the heuristics in ``chat_intent.classify`` so a future refactor
that breaks "how many" / "list all" / "how is A related to B"
detection fails loudly. All tests stub the Postgres helpers so they
run on the host without a database.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app import chat_intent


WORKSPACE_TYPES = ["Location", "Organization", "Standard"]

WORKSPACE_ENTITIES = [
    {"id": "1", "canonical_name": "Deloitte", "type": "Organization"},
    {"id": "2", "canonical_name": "MRP-227", "type": "Standard"},
    {
        "id": "3",
        "canonical_name": "Probabilistic Safety Assessment",
        "type": "Concept",
    },
    {"id": "4", "canonical_name": "EPRI", "type": "Organization"},
]


@pytest.fixture
def patched_db():
    with patch(
        "app.chat_intent._list_entity_types", return_value=WORKSPACE_TYPES
    ), patch(
        "app.chat_intent._list_entity_names", return_value=WORKSPACE_ENTITIES
    ):
        yield


def test_aggregation_how_many(patched_db) -> None:
    r = chat_intent.classify(
        "postgresql://stub/none",
        workspace_id="x",
        query_text="How many Locations are mentioned in this workspace?",
    )
    assert r.kind == "aggregation"
    assert "Location" in r.slots.entity_types


def test_aggregation_list_all(patched_db) -> None:
    r = chat_intent.classify(
        "postgresql://stub/none",
        workspace_id="x",
        query_text="List all Standards mentioned in this paper.",
    )
    assert r.kind == "aggregation"
    assert "Standard" in r.slots.entity_types


def test_multi_hop_requires_two_mentions(patched_db) -> None:
    r = chat_intent.classify(
        "postgresql://stub/none",
        workspace_id="x",
        query_text="How is Deloitte related to MRP-227?",
    )
    assert r.kind == "multi_hop"
    assert set(r.slots.mentioned_entities) == {"Deloitte", "MRP-227"}


def test_multi_hop_falls_back_to_vector_with_one_mention(patched_db) -> None:
    r = chat_intent.classify(
        "postgresql://stub/none",
        workspace_id="x",
        query_text="What is the relationship between Deloitte and oil-and-gas operators?",
    )
    # Only "Deloitte" matches the workspace entity list; with <2
    # mentions the router defers to vector retrieval.
    assert r.kind == "vector"
    assert r.slots.mentioned_entities == ["Deloitte"]


def test_plain_question_is_vector(patched_db) -> None:
    r = chat_intent.classify(
        "postgresql://stub/none",
        workspace_id="x",
        query_text="What does MRP-227 say about reactor coolant materials?",
    )
    assert r.kind == "vector"


def test_empty_query_is_refusal_or_unknown(patched_db) -> None:
    r = chat_intent.classify(
        "postgresql://stub/none", workspace_id="x", query_text="   "
    )
    assert r.kind == "refusal_or_unknown"


def test_aggregation_takes_priority_over_multi_hop(patched_db) -> None:
    # "How many Organizations connect to MRP-227" parses as aggregation
    # because the "how many" pattern fires before the multi-hop pattern.
    r = chat_intent.classify(
        "postgresql://stub/none",
        workspace_id="x",
        query_text="How many Organizations connect to MRP-227?",
    )
    assert r.kind == "aggregation"
