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

from app.ontology_autotune import SAMPLE_INDEX_KINDS

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
                # encoding_format=float fixes the arrow error; dimensions pins 1536
                # (see spikes/ms-graphrag/README.md). litellm needs embed-v4.0
                # registered to permit `dimensions` — handled in run_graphrag_index.
                "call_args": {"encoding_format": "float", "dimensions": int(embed_dim)},
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


def _register_cohere_embed_dimensions(model: str) -> None:
    """Permit the `dimensions` embedding param for a Cohere embed model in litellm.

    litellm rejects `dimensions` for non text-embedding-3 models on the openai
    provider, but Cohere's compat endpoint honors it. Best-effort registration;
    swallow API differences (validated on the graphrag-worker).
    """
    try:  # pragma: no cover - exercised on the graphrag-worker, not in unit tests
        import litellm

        litellm.register_model(
            {model: {"mode": "embedding", "supports_dimensions": True, "litellm_provider": "openai"}}
        )
    except Exception:  # noqa: BLE001
        pass


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
    _register_cohere_embed_dimensions(embed_model)

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
