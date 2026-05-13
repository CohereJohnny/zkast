"""Sprint 6 + TD-015 — graph-context grounding document.

``chat_turn._retrieve`` now prepends a synthetic
``graph_context:workspace_shape`` document to every grounding bundle so
the LLM has ground-truth aggregates (type counts + named exemplars)
even when the hybrid ranker misses the relevant entities. Without this,
questions like "how many locations are mentioned" can only be answered
from the vector-similar fact snippets — which are the wrong unit for
typed aggregation.

This test pins three contract points:

1. The graph-context document is included in the documents list passed
   to Cohere.
2. ``summarize_workspace_graph`` is the source of its content (so a
   future refactor that drops the import breaks loudly).
3. The render function produces a text body that names the per-type
   exemplars and surfaces the per-type counts.
"""

from __future__ import annotations

from app import chat_turn
from app.filter_options_repo import summarize_workspace_graph as _summarize_export


def test_summarize_workspace_graph_is_imported_by_chat_turn() -> None:
    assert chat_turn.summarize_workspace_graph is _summarize_export


def test_render_graph_context_document_emits_counts_and_names() -> None:
    shape = {
        "entity_total": 117,
        "edge_total": 67,
        "entity_types": [
            {
                "name": "Process",
                "count": 48,
                "top_examples": [
                    "Hydraulic Fracturing",
                    "Refining",
                    "Drilling",
                ],
                "truncated_examples": True,
            },
            {
                "name": "Location",
                "count": 6,
                "top_examples": [
                    "North America",
                    "Asia-Pacific",
                    "Middle East",
                    "Australia",
                    "Canada",
                    "Japan",
                ],
                "truncated_examples": False,
            },
        ],
        "edge_types": [
            {"name": "RELATES_TO", "count": 48},
            {"name": "CITES", "count": 7},
        ],
    }

    rendered = chat_turn._render_graph_context_document(shape)

    assert "Total entities: 117" in rendered
    assert "Total relationships: 67" in rendered
    # Type with truncated examples surfaces the count and the "showing
    # first N of M" hint.
    assert "Process (count=48)" in rendered
    assert "showing first 3 of 48" in rendered
    # Type with all 6 names should list every one so an aggregation query
    # can answer correctly (the user-reported bug — chat missed the 6
    # Locations because vector retrieval surfaced unrelated facts).
    assert "Location (count=6)" in rendered
    for name in (
        "North America",
        "Asia-Pacific",
        "Middle East",
        "Australia",
        "Canada",
        "Japan",
    ):
        assert name in rendered, f"Location example {name!r} missing from rendering"
    # Relationship-type counts are present so the LLM can reason about
    # graph topology when asked.
    assert "RELATES_TO (count=48)" in rendered
    # And the instructional postamble that tells the LLM to treat the
    # structured numbers as authoritative.
    assert "authoritative" in rendered


def test_render_graph_context_document_returns_empty_for_empty_workspace() -> None:
    """Empty workspaces must skip the synthetic document so the refusal
    short-circuit in ``run_chat_turn`` still fires correctly."""
    assert chat_turn._render_graph_context_document({"entity_total": 0}) == ""
    assert chat_turn._render_graph_context_document({}) == ""
