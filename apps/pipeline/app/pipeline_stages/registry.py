"""Registries of stage plugins + the built-in default configuration.

Plugins are registered as metadata (lazy module/attr hints) so importing the
registry stays cheap and does not pull in heavy retrieval modules. Resolution
helpers import the target lazily.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable

from app.pipeline_stages.base import (
    PipelineConfiguration,
    StageKind,
    StagePlugin,
)

# --- Extractor engines -------------------------------------------------------
EXTRACTORS: dict[str, StagePlugin] = {
    "graphiti": StagePlugin(
        id="graphiti",
        kind=StageKind.EXTRACT,
        label="Graphiti typed extraction",
        description="LLM typed entity/edge extraction via graphiti-core, with the LangExtract grounding co-extractor.",
        implemented=True,
    ),
    "langextract": StagePlugin(
        id="langextract",
        kind=StageKind.EXTRACT,
        label="LangExtract grounded extraction",
        description="Schema'd, character-grounded entity/relationship extraction as a first-class extractor.",
        implemented=False,
    ),
    "ms_graphrag": StagePlugin(
        id="ms_graphrag",
        kind=StageKind.EXTRACT,
        label="Microsoft GraphRAG native extraction",
        description="Batch community-based extraction over a corpus.",
        implemented=False,
    ),
}

# --- Graph stores / indexes --------------------------------------------------
GRAPH_STORES: dict[str, StagePlugin] = {
    "graphiti_falkor": StagePlugin(
        id="graphiti_falkor",
        kind=StageKind.STORE,
        label="Graphiti + FalkorDB",
        description="Live graph in FalkorDB mirrored to Postgres entities/relationships.",
        implemented=True,
    ),
    "graphrag_artifacts": StagePlugin(
        id="graphrag_artifacts",
        kind=StageKind.STORE,
        label="GraphRAG artifacts",
        description="Parquet entities/relationships + community reports + vector store.",
        implemented=False,
    ),
}

# --- Retrieval strategies (mirror chat_turn._retrieve dispatch) --------------
RETRIEVERS: dict[str, StagePlugin] = {
    "graph": StagePlugin(
        id="graph",
        kind=StageKind.RETRIEVE,
        label="GraphRAG (Graphiti)",
        description="Graphiti hybrid search over graph artifacts + graph-context document.",
        module="app.chat_retrieval_graph",
        attr="retrieve",
        strategy="graph_graphiti_context_v1",
        implemented=True,
    ),
    "rag": StagePlugin(
        id="rag",
        kind=StageKind.RETRIEVE,
        label="Naive RAG (raw chunks)",
        description="pgvector over raw_chunk embeddings only.",
        module="app.chat_retrieval_raw",
        attr="retrieve",
        strategy="rag_raw_chunk_v1",
        implemented=True,
    ),
    "raw_transcript": StagePlugin(
        id="raw_transcript",
        kind=StageKind.RETRIEVE,
        label="Naive RAG (raw transcript)",
        description="Naive RAG alias used in transcript evals.",
        module="app.chat_retrieval_raw",
        attr="retrieve",
        strategy="rag_raw_chunk_v1",
        implemented=True,
    ),
    "hybrid": StagePlugin(
        id="hybrid",
        kind=StageKind.RETRIEVE,
        label="Hybrid (traversal + evidence)",
        description="Deterministic typed/multi-hop handlers plus graph evidence.",
        module="app.chat_retrieval_hybrid",
        attr="retrieve",
        strategy="hybrid_typed_entity_v1",
        implemented=True,
    ),
    "zettelkasten_notes": StagePlugin(
        id="zettelkasten_notes",
        kind=StageKind.RETRIEVE,
        label="Zettelkasten notes (vector)",
        description="pgvector over note_zettel embeddings.",
        module="app.chat_retrieval_notes_vector",
        attr="retrieve_zettel",
        strategy="notes_vector_zettel_v1",
        implemented=True,
    ),
    "amem_lite": StagePlugin(
        id="amem_lite",
        kind=StageKind.RETRIEVE,
        label="A-MEM lite (vector)",
        description="pgvector over note_amem embeddings.",
        module="app.chat_retrieval_notes_vector",
        attr="retrieve_amem",
        strategy="notes_vector_amem_v1",
        implemented=True,
    ),
    "ms_graphrag": StagePlugin(
        id="ms_graphrag",
        kind=StageKind.RETRIEVE,
        label="Microsoft GraphRAG (community search)",
        description="Local/global search over GraphRAG community reports.",
        module="app.chat_retrieval_ms_graphrag",
        attr="retrieve",
        strategy="graph_ms_graphrag_v1",
        implemented=False,
    ),
    "wiki": StagePlugin(
        id="wiki",
        kind=StageKind.RETRIEVE,
        label="Wiki (eval stub)",
        description="Eval-only placeholder until wiki pages are indexed for retrieval.",
        module="app.chat_retrieval_wiki",
        attr="retrieve",
        strategy="wiki_stub",
        implemented=True,
    ),
}


def resolve_retriever(retrieval_strategy: str) -> Callable[..., Any]:
    """Lazily import and return a retriever's ``retrieve`` coroutine.

    Mirrors today's chat_turn._retrieve dispatch so a later slice can route
    through the registry without behavior change.
    """
    plugin = RETRIEVERS.get((retrieval_strategy or "graph").strip().lower())
    if plugin is None or not plugin.module or not plugin.attr:
        plugin = RETRIEVERS["graph"]
    if not plugin.implemented:
        raise NotImplementedError(f"retriever '{plugin.id}' is registered but not implemented")
    module = importlib.import_module(plugin.module)
    return getattr(module, plugin.attr)


def resolve_extractor(extractor_id: str) -> StagePlugin:
    """Return the registered extractor plugin or raise.

    Seam for the future multi-extractor dispatch (Graphiti vs MS GraphRAG vs
    LangExtract). The heavy ``extract_graph`` body is rewired to call through
    here once a second extractor exists; today only ``graphiti`` is implemented.
    """
    plugin = EXTRACTORS.get((extractor_id or "graphiti").strip().lower())
    if plugin is None:
        raise ValueError(f"unknown extractor: {extractor_id!r}")
    if not plugin.implemented:
        raise NotImplementedError(f"extractor '{plugin.id}' is registered but not implemented")
    return plugin


# --- Built-in default configuration (the current production pipeline) --------
BUILTIN_DEFAULT = PipelineConfiguration(
    name="builtin-default",
    description="Current production pipeline: Graphiti typed extraction (generic ontology) + Graphiti/FalkorDB store + graph retrieval.",
    extractor="graphiti",
    graph_store="graphiti_falkor",
    retrieval_strategy="graph",
    ontology_version="generic_v1",
    provider="cohere_compat",
    is_builtin=True,
    version=1,
)
