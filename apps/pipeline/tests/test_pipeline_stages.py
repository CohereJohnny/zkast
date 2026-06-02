"""Stage registry + Pipeline Configuration model (composable eval harness)."""

from pathlib import Path

import pytest
import yaml

from app.pipeline_stages.base import PipelineConfiguration, compute_content_hash
from app.pipeline_stages.registry import (
    BUILTIN_DEFAULT,
    EXTRACTORS,
    GRAPH_STORES,
    RETRIEVERS,
)


def test_registry_has_current_builtins() -> None:
    # Current production stack must be registered + implemented.
    assert EXTRACTORS["graphiti"].implemented
    assert GRAPH_STORES["graphiti_falkor"].implemented
    for mode in ("graph", "rag", "raw_transcript", "hybrid", "zettelkasten_notes", "amem_lite"):
        assert RETRIEVERS[mode].implemented, mode
    # Planned plugins are registered but flagged not implemented.
    assert not EXTRACTORS["ms_graphrag"].implemented
    assert not GRAPH_STORES["graphrag_artifacts"].implemented
    assert not RETRIEVERS["ms_graphrag"].implemented


def test_retriever_strategy_strings_match_current_pipeline() -> None:
    assert RETRIEVERS["graph"].strategy == "graph_graphiti_context_v1"
    assert RETRIEVERS["rag"].strategy == "rag_raw_chunk_v1"
    assert RETRIEVERS["zettelkasten_notes"].strategy == "notes_vector_zettel_v1"
    assert RETRIEVERS["amem_lite"].strategy == "notes_vector_amem_v1"


def test_content_hash_is_deterministic_and_sensitive() -> None:
    a = PipelineConfiguration(
        name="a", extractor="graphiti", graph_store="graphiti_falkor",
        retrieval_strategy="graph", ontology_version="generic_v1",
    )
    b = PipelineConfiguration(
        name="different-name-same-composition", extractor="graphiti",
        graph_store="graphiti_falkor", retrieval_strategy="graph",
        ontology_version="generic_v1",
    )
    # Name/description do not affect identity; composition does.
    assert a.content_hash == b.content_hash
    c = PipelineConfiguration(
        name="a", extractor="graphiti", graph_store="graphiti_falkor",
        retrieval_strategy="ms_graphrag", ontology_version="generic_v1",
    )
    assert c.content_hash != a.content_hash


def test_builtin_default_round_trips_doc() -> None:
    doc = BUILTIN_DEFAULT.to_doc()
    restored = PipelineConfiguration.from_doc(doc)
    assert restored.content_hash == BUILTIN_DEFAULT.content_hash
    assert restored.extractor == "graphiti"
    assert restored.retrieval_strategy == "graph"


def test_resolve_retriever_matches_prior_dispatch() -> None:
    """The registry must resolve each mode to the SAME callable as the prior
    chat_turn._retrieve inline dispatch (no behavior change)."""
    from app import chat_retrieval_graph, chat_retrieval_hybrid, chat_retrieval_raw
    from app.chat_retrieval_notes_vector import retrieve_amem, retrieve_zettel
    from app.pipeline_stages.registry import resolve_retriever

    assert resolve_retriever("graph") is chat_retrieval_graph.retrieve
    assert resolve_retriever("rag") is chat_retrieval_raw.retrieve
    assert resolve_retriever("raw_transcript") is chat_retrieval_raw.retrieve
    assert resolve_retriever("hybrid") is chat_retrieval_hybrid.retrieve
    assert resolve_retriever("zettelkasten_notes") is retrieve_zettel
    assert resolve_retriever("amem_lite") is retrieve_amem
    # Unknown/empty falls back to graph, matching the prior `else` branch.
    assert resolve_retriever("") is chat_retrieval_graph.retrieve
    assert resolve_retriever("nonsense") is chat_retrieval_graph.retrieve


def test_eval_adapter_routes_via_registry() -> None:
    """eval/adapters.retrieval_module resolves through the same registry, incl.
    alias normalization and the wiki stub; unknown modes raise."""
    from app import chat_retrieval_graph, chat_retrieval_raw, chat_retrieval_wiki
    from app.chat_retrieval_notes_vector import retrieve_zettel
    from app.eval.adapters import retrieval_module

    assert retrieval_module("graph").retrieve is chat_retrieval_graph.retrieve
    assert retrieval_module("raw").retrieve is chat_retrieval_raw.retrieve  # alias -> rag
    assert retrieval_module("zettel").retrieve is retrieve_zettel  # alias -> zettelkasten_notes
    assert retrieval_module("wiki").retrieve is chat_retrieval_wiki.retrieve
    with pytest.raises(ValueError):
        retrieval_module("does_not_exist")


def test_resolve_extractor() -> None:
    from app.pipeline_stages.registry import resolve_extractor

    assert resolve_extractor("graphiti").id == "graphiti"
    with pytest.raises(NotImplementedError):
        resolve_extractor("ms_graphrag")
    with pytest.raises(ValueError):
        resolve_extractor("nope")


def test_builtin_default_matches_seed_yaml() -> None:
    seed_path = Path(__file__).resolve().parent.parent / "app" / "pipeline_configs" / "builtin-default.yaml"
    doc = yaml.safe_load(seed_path.read_text())
    from_yaml = PipelineConfiguration.from_doc(doc)
    # The YAML seed and the code default must describe the same composition,
    # so the migration-seeded row and the registry agree.
    assert from_yaml.content_hash == BUILTIN_DEFAULT.content_hash
