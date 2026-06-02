"""Dedicated graphrag-worker: MS GraphRAG batch index jobs.

Runs in its own container image (python 3.12 + graphrag + openai 2.x), isolated
from the main pipeline's openai<2 deps. This module is intentionally
**graphiti-free** — it imports only the indexer, the index repo, config, secrets,
and workspace_repo, so the graphrag image can install a minimal dep set (no
graphiti-core / langextract / cohere / pymupdf).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import structlog
from arq.connections import RedisSettings
from arq.worker import func as arq_func

from app.config import get_settings
from app.graphrag_index_repo import mark_failed, mark_ready, mark_running
from app.graphrag_indexer import EMBED_DIM, export_corpus, run_graphrag_index
from app.graphrag_reports_repo import persist_community_reports
from app.queues import GRAPHRAG_QUEUE_NAME
from app.secrets import decrypt
from app.workspace_repo import fetch_llm_cohere_secret_row, fetch_pipeline_settings

logger = structlog.get_logger(__name__)

# Source of truth: app.graphiti_factory.COHERE_COMPAT_BASE (duplicated here to
# keep this module graphiti-free for the minimal graphrag image).
COHERE_COMPAT_BASE = "https://api.cohere.com/compatibility/v1"

TIMEOUT_GRAPHRAG_INDEX_S = 3_600
STORAGE_DIR = os.getenv("GRAPHRAG_STORAGE_DIR", "/var/zkast/graphrag")


def _resolve_cohere_key(settings: Any, workspace_id: str) -> str | None:
    if settings.cohere_api_key and settings.cohere_api_key.strip():
        return settings.cohere_api_key.strip()
    enc = fetch_llm_cohere_secret_row(settings.database_url, workspace_id)
    if not enc:
        return None
    return decrypt(settings.master_encryption_key_bytes, enc).decode("utf-8")


async def run_graphrag_index_job(
    ctx: dict[str, Any],
    *,
    index_id: str,
    workspace_id: str,
    agent_id: str | None = None,
    configuration_id: str | None = None,
    ontology_name: str | None = None,
    ontology_version: str | None = None,
    max_docs: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    db = settings.database_url
    mark_running(db, index_id=index_id)
    try:
        api_key = _resolve_cohere_key(settings, workspace_id)
        if not api_key:
            raise RuntimeError("No Cohere API key configured for this workspace")
        pipe = fetch_pipeline_settings(db, workspace_id)
        chat_model = str(pipe.get("large_model") or "command-a-plus-05-2026")
        embed_model = str(pipe.get("embed_model") or "embed-v4.0")

        documents = export_corpus(
            db, workspace_id=workspace_id, agent_id=agent_id, max_docs=max_docs
        )
        if not documents:
            raise RuntimeError("No corpus to index for the selected scope")

        root = Path(STORAGE_DIR) / index_id
        os.environ["GRAPHRAG_API_KEY"] = api_key
        logger.info(
            "graphrag_index_start",
            index_id=index_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            documents=len(documents),
        )
        result = await run_graphrag_index(
            root=root,
            documents=documents,
            base_url=COHERE_COMPAT_BASE,
            chat_model=chat_model,
            embed_model=embed_model,
            embed_dim=EMBED_DIM,
        )
        if result["ok"]:
            n_reports = persist_community_reports(
                db,
                graphrag_index_id=index_id,
                workspace_id=workspace_id,
                agent_id=agent_id,
                reports=result.get("community_reports", []),
            )
            mark_ready(db, index_id=index_id, artifact_uri=result["artifact_uri"], stats=result["stats"])
            logger.info(
                "graphrag_index_ready", index_id=index_id, reports=n_reports, stats=result["stats"]
            )
        else:
            failed = ", ".join(result["stats"].get("failed_workflows", []))
            mark_failed(db, index_id=index_id, reason=f"GraphRAG workflows failed: {failed}")
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("graphrag_index_failed", index_id=index_id, error=str(exc))
        mark_failed(db, index_id=index_id, reason=f"{type(exc).__name__}: {exc}")
        raise


def _redis_settings() -> RedisSettings:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    rs = RedisSettings.from_dsn(url)
    rs.conn_timeout = 10
    return rs


class GraphragWorkerSettings:
    """arq worker consuming the dedicated GraphRAG queue."""

    queue_name = GRAPHRAG_QUEUE_NAME
    redis_settings = _redis_settings()
    functions = [arq_func(run_graphrag_index_job, timeout=TIMEOUT_GRAPHRAG_INDEX_S, max_tries=1)]
    job_timeout = TIMEOUT_GRAPHRAG_INDEX_S
    # Index runs are heavy + sequential; one at a time.
    max_jobs = int(os.getenv("GRAPHRAG_WORKER_MAX_JOBS", "1"))
