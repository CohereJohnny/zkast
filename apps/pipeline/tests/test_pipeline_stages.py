"""Stage registry + Pipeline Configuration model (composable eval harness)."""

from pathlib import Path

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


def test_builtin_default_matches_seed_yaml() -> None:
    seed_path = Path(__file__).resolve().parent.parent / "app" / "pipeline_configs" / "builtin-default.yaml"
    doc = yaml.safe_load(seed_path.read_text())
    from_yaml = PipelineConfiguration.from_doc(doc)
    # The YAML seed and the code default must describe the same composition,
    # so the migration-seeded row and the registry agree.
    assert from_yaml.content_hash == BUILTIN_DEFAULT.content_hash
