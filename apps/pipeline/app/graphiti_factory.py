"""Construct Graphiti with FalkorDB + Cohere (Command compat, Embed + Rerank per workspace settings)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import structlog
from graphiti_core import Graphiti
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.nodes import EpisodeType

from app.cohere_adapters import CohereCrossEncoder, CohereEmbedder
from app.config import Settings
from app.memory_space import falkor_database_for_memory_space, memory_space_graph_name
from app.secrets import decrypt
from app.workspace_repo import fetch_llm_cohere_secret_row, fetch_pipeline_settings

logger = structlog.get_logger(__name__)

COHERE_COMPAT_BASE = "https://api.cohere.com/compatibility/v1"


def falkor_database_for_workspace(
    workspace_id: str,
    agent_id: str | None = None,
    collection_id: str | None = None,
) -> str:
    """FalkorDB graph name; must match Graphiti ``group_id`` for reads/writes."""
    return falkor_database_for_memory_space(workspace_id, agent_id, collection_id)


def resolve_stored_cohere_api_key(settings: Settings, workspace_id: str) -> str | None:
    """Decrypt workspace llm_cohere row only (no env bypass)."""
    enc = fetch_llm_cohere_secret_row(settings.database_url, workspace_id)
    if not enc:
        return None
    return decrypt(settings.master_encryption_key_bytes, enc).decode("utf-8")


def resolve_cohere_api_key(settings: Settings, workspace_id: str) -> str | None:
    """Env `COHERE_API_KEY` overrides DB when set (local dev convenience)."""
    if settings.cohere_api_key and settings.cohere_api_key.strip():
        return settings.cohere_api_key.strip()
    return resolve_stored_cohere_api_key(settings, workspace_id)


def build_graphiti(
    settings: Settings,
    *,
    workspace_id: str,
    api_key: str,
    pipeline: dict[str, object],
    agent_id: str | None = None,
    collection_id: str | None = None,
    semaphore_limit: int | None = None,
) -> Graphiti:
    os.environ.setdefault("GRAPHITI_TELEMETRY_ENABLED", "false")

    driver = FalkorDriver(
        host=settings.falkordb_host,
        port=settings.falkordb_port,
        database=falkor_database_for_workspace(workspace_id, agent_id, collection_id),
    )

    llm_cfg = LLMConfig(
        api_key=api_key,
        base_url=COHERE_COMPAT_BASE,
        model=str(pipeline["large_model"]),
        small_model=str(pipeline["small_model"]),
        temperature=0.3,
    )
    llm = OpenAIGenericClient(config=llm_cfg)

    embed_dim = int(os.getenv("EMBEDDING_DIM", "1536"))
    embedder = CohereEmbedder(
        api_key=api_key,
        model=str(pipeline["embed_model"]),
        embedding_dim=embed_dim,
    )
    reranker = CohereCrossEncoder(
        api_key=api_key,
        model=str(pipeline["rerank_model"]),
    )

    max_coroutines = semaphore_limit
    if max_coroutines is None:
        raw = os.getenv("SEMAPHORE_LIMIT", "").strip()
        if raw.isdigit():
            max_coroutines = max(1, int(raw))
        else:
            max_coroutines = 10

    return Graphiti(
        graph_driver=driver,
        llm_client=llm,
        embedder=embedder,
        cross_encoder=reranker,
        max_coroutines=max_coroutines,
    )


async def graphiti_for_workspace(
    settings: Settings,
    workspace_id: str,
    agent_id: str | None = None,
    collection_id: str | None = None,
) -> Graphiti:
    api_key = resolve_cohere_api_key(settings, workspace_id)
    if not api_key:
        raise ValueError("No Cohere API key (set COHERE_API_KEY or save llm_cohere in workspace)")
    pipeline = fetch_pipeline_settings(settings.database_url, workspace_id)
    g = build_graphiti(
        settings,
        workspace_id=workspace_id,
        api_key=api_key,
        pipeline=pipeline,
        agent_id=agent_id,
        collection_id=collection_id,
    )
    await g.build_indices_and_constraints()
    graph_name = memory_space_graph_name(workspace_id, agent_id, collection_id)
    logger.info(
        "graphiti_ready",
        workspace_id=workspace_id,
        agent_id=agent_id,
        collection_id=collection_id,
        falkor_db=graph_name,
    )
    return g


async def run_synthetic_episode_smoke(
    graphiti: Graphiti, *, group_id: str | None = None
) -> None:
    """Add one text episode and run a hybrid search (raises on Graphiti/provider errors)."""
    gid = group_id or "zkast-default"
    await graphiti.add_episode(
        name="zkast-synthetic-smoke",
        episode_body=(
            "Alice Example founded ExampleCorp in 2020. "
            "ExampleCorp released the GraphTest product in 2022."
        ),
        source_description="synthetic transcript",
        reference_time=datetime.now(timezone.utc),
        source=EpisodeType.text,
        group_id=gid,
    )
    results = await graphiti.search("Who founded ExampleCorp?", group_ids=[gid])
    if not results:
        logger.warning("graphiti_smoke_empty_search")
