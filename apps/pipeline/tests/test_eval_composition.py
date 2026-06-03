"""Eval composition recording + stage attribution."""

from app.eval.composition import composition_for_mode, diff_stages


def test_composition_defaults_to_builtin_stages() -> None:
    c = composition_for_mode("graph")
    assert c["extractor"] == "graphiti"
    assert c["graph_store"] == "graphiti_falkor"
    assert c["ontology_version"] == "generic_v1"
    assert c["provider"] == "cohere_compat"
    assert c["retrieval_strategy"] == "graph"
    assert isinstance(c["content_hash"], str) and len(c["content_hash"]) == 64


def test_composition_normalizes_alias() -> None:
    assert composition_for_mode("raw")["retrieval_strategy"] == "rag"


def test_retrieval_change_changes_hash_and_attributes_to_stage() -> None:
    graph = composition_for_mode("graph")
    msg = composition_for_mode("ms_graphrag")
    assert graph["content_hash"] != msg["content_hash"]
    # Only the retrieval stage differs -> attributable to retrieval_strategy.
    assert diff_stages(graph, msg) == ["retrieval_strategy"]


def test_ontology_override_attributes_to_ontology() -> None:
    generic = composition_for_mode("graph")
    tuned = composition_for_mode("graph", {"ontology_version": "nuclear_v1"})
    assert generic["content_hash"] != tuned["content_hash"]
    assert diff_stages(generic, tuned) == ["ontology_version"]
