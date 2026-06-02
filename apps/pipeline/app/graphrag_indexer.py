"""MS GraphRAG indexer: export a memory space's corpus, generate an all-Cohere
GraphRAG config, and build the index.

Runs on the dedicated ``graphrag-worker`` (graphrag + openai 2.x). The heavy
``graphrag`` import is kept lazy so this module loads anywhere (incl. the main
pipeline image on openai 1.x); only ``run_graphrag_index`` requires graphrag.

Per the spike (spikes/ms-graphrag/README.md): everything stays on Cohere's
OpenAI-compatibility endpoint; the embedding model needs ``encoding_format:
float`` and is pinned to 1536 dims (the workspace-wide embedding standard) so
local_search's query/stored vectors agree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
import yaml

# Kept local (not imported from ontology_autotune) so this module stays free of
# graphiti_core for the minimal graphrag-worker image. Mirrors
# ontology_autotune.SAMPLE_INDEX_KINDS.
SAMPLE_INDEX_KINDS: tuple[str, ...] = ("raw_chunk", "note_zettel")

EMBED_DIM = 1536
# Match the harness graph ontology so GraphRAG extraction is comparable.
DEFAULT_ENTITY_TYPES = [
    "organization",
    "person",
    "geo",
    "event",
    "standard",
    "equipment",
    "process",
    "material",
]


def export_corpus(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str | None = None,
    kinds: tuple[str, ...] = SAMPLE_INDEX_KINDS,
    max_chars: int = 8000,
    max_docs: int | None = None,
) -> list[dict[str, str]]:
    """All corpus text for a memory space as GraphRAG input documents.

    Scope precedence mirrors auto-tune: a single ``agent_id`` (memory space) or
    the whole workspace when None. Returns ``[{id, text}]``.
    """
    sql = [
        "SELECT id::text AS id, text FROM retrieval_embeddings",
        "WHERE workspace_id = %s::uuid AND index_kind = ANY(%s)",
    ]
    args: list[Any] = [workspace_id, list(kinds)]
    if agent_id:
        sql.append("AND agent_id = %s::uuid")
        args.append(agent_id)
    sql.append("ORDER BY created_at ASC")
    if max_docs:
        sql.append("LIMIT %s")
        args.append(int(max_docs))
    with psycopg.connect(database_url) as conn:
        rows = conn.execute("\n".join(sql), tuple(args)).fetchall()
    return [{"id": str(r[0]), "text": str(r[1])[:max_chars]} for r in rows if r and r[1]]


def build_graphrag_settings(
    *,
    base_url: str,
    chat_model: str,
    embed_model: str,
    entity_types: list[str] | None = None,
    embed_dim: int = EMBED_DIM,
) -> dict[str, Any]:
    """GraphRAG 3.1.0 settings dict for an all-Cohere-compat run.

    The api key is supplied via the ``GRAPHRAG_API_KEY`` env (token replacement).
    Embeddings force ``encoding_format: float`` (avoids graphrag's arrow assembly
    error) and ``dimensions`` = embed_dim so index/query vectors agree (1536).
    """
    model_common = {
        "model_provider": "openai",
        "api_base": base_url,
        "auth_method": "api_key",
        "api_key": "${GRAPHRAG_API_KEY}",
        "retry": {"type": "exponential_backoff"},
    }
    return {
        "completion_models": {
            "default_completion_model": {
                **model_common,
                "model": chat_model,
                "model_supports_json": True,
            }
        },
        "embedding_models": {
            "default_embedding_model": {
                **model_common,
                "model": embed_model,
                # encoding_format=float is REQUIRED (avoids graphrag's arrow
                # assembly error). NOTE: we cannot pin `dimensions` here — litellm
                # rejects it for embed-v4.0 on the openai provider. The model
                # returns 1536 for a normal call, but graphrag stores a 3072-dim
                # entity_description vector (it concatenates name+description
                # embeddings) while local_search queries at 1536 -> dim mismatch.
                # global_search is unaffected. Tracked: local_search needs graphrag
                # entity-embedding consistency (see spikes/ms-graphrag/README.md).
                "call_args": {"encoding_format": "float"},
            }
        },
        "input": {"type": "text"},
        "input_storage": {"type": "file", "base_dir": "input"},
        "output_storage": {"type": "file", "base_dir": "output"},
        "cache": {"type": "json", "storage": {"type": "file", "base_dir": "cache"}},
        "vector_store": {"type": "lancedb", "db_uri": "output/lancedb"},
        "extract_graph": {
            "entity_types": entity_types or DEFAULT_ENTITY_TYPES,
            "max_gleanings": 1,
        },
    }


def write_workspace(root: Path, settings: dict[str, Any], documents: list[dict[str, str]]) -> None:
    """Write settings.yaml + input/<id>.txt under ``root`` for a GraphRAG run."""
    root.mkdir(parents=True, exist_ok=True)
    input_dir = root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    (root / "settings.yaml").write_text(yaml.safe_dump(settings, sort_keys=False))
    for doc in documents:
        (input_dir / f"{doc['id']}.txt").write_text(doc["text"])


async def run_graphrag_index(
    *,
    root: Path,
    documents: list[dict[str, str]],
    base_url: str,
    chat_model: str,
    embed_model: str,
    entity_types: list[str] | None = None,
    embed_dim: int = EMBED_DIM,
) -> dict[str, Any]:
    """Write the workspace, run GraphRAG build_index, return artifact stats.

    Lazy-imports graphrag (only available on the graphrag-worker). The caller
    must set the GRAPHRAG_API_KEY env to the resolved provider key.
    """
    import pandas as pd  # noqa: WPS433 - heavy, worker-only
    from graphrag.api import build_index  # noqa: WPS433
    from graphrag.config.load_config import load_config  # noqa: WPS433

    settings = build_graphrag_settings(
        base_url=base_url,
        chat_model=chat_model,
        embed_model=embed_model,
        entity_types=entity_types,
        embed_dim=embed_dim,
    )
    write_workspace(root, settings, documents)

    config = load_config(root)
    results = await build_index(config=config, verbose=False)
    failed = [r for r in results if getattr(r, "errors", None)]

    out = root / "output"

    def _count(name: str) -> int:
        path = out / f"{name}.parquet"
        return int(len(pd.read_parquet(path))) if path.exists() else 0

    stats = {
        "documents": len(documents),
        "entities": _count("entities"),
        "relationships": _count("relationships"),
        "communities": _count("communities"),
        "community_reports": _count("community_reports"),
        "text_units": _count("text_units"),
        "failed_workflows": [getattr(r, "workflow", "?") for r in failed],
    }
    return {"artifact_uri": str(out), "stats": stats, "ok": not failed}
