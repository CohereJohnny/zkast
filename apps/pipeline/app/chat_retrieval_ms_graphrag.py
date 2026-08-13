"""MS GraphRAG retrieval (global-search style).

Grounds the chat turn on the community reports of the latest READY GraphRAG index
for the memory space — mirroring GraphRAG's global search, which reasons over
community reports rather than entity-vector similarity. Reads the reports from
Postgres (persisted by the graphrag-worker), so this runs on the chat-worker with
no graphrag/pandas dependency.

local_search (entity-vector) is intentionally NOT used here: GraphRAG stores a
3072-dim entity vector while querying at 1536 (see spikes/ms-graphrag/README.md);
global search needs no entity vectors and works on Cohere today.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.cohere_chat import ChatDocument
from app.graphrag_reports_repo import fetch_reports_for_space

logger = structlog.get_logger(__name__)

MS_GRAPHRAG_STRATEGY = "graph_ms_graphrag_v1"
APPROX_CHARS_PER_TOKEN = 4


async def retrieve(
    settings: Any,
    database_url: str,
    *,
    workspace_id: str,
    query_text: str,
    scope: dict[str, Any],
    top_k: int,
    doc_token_budget: int,
) -> tuple[list[dict[str, Any]], list[ChatDocument], int, bool, str]:
    agent_id = (
        str(scope.get("agent_id")).strip() if scope.get("agent_id") else None
    )
    collection_id = (
        None
        if agent_id
        else (str(scope.get("collection_id")).strip() if scope.get("collection_id") else None)
    )
    limit = min(max(int(top_k), 8), 20)
    reports = await asyncio.to_thread(
        fetch_reports_for_space,
        database_url,
        workspace_id=workspace_id,
        agent_id=agent_id,
        collection_id=collection_id,
        limit=limit,
    )
    if not reports:
        logger.info(
            "ms_graphrag_no_index",
            workspace_id=workspace_id,
            agent_id=agent_id,
            collection_id=collection_id,
        )
        return [], [], 0, False, MS_GRAPHRAG_STRATEGY

    budget_chars = doc_token_budget * APPROX_CHARS_PER_TOKEN
    used_chars = 0
    truncated = False
    items: list[dict[str, Any]] = []
    documents: list[ChatDocument] = []

    for r in reports:
        content = (r.get("full_content") or r.get("summary") or "")[:4000]
        if not content.strip():
            continue
        if used_chars + len(content) > budget_chars and documents:
            truncated = True
            break
        used_chars += len(content)
        community = r.get("community")
        title = r.get("title") or f"Community {community}"
        items.append(
            {
                "kind": "graphrag_community_report",
                "community": community,
                "level": r.get("level"),
                "rank": r.get("rank"),
                "title": title,
                "excerpt": content[:500],
            }
        )
        documents.append(
            ChatDocument(
                id=f"graphrag_report:{community}",
                text=content,
                title=title,
                metadata={
                    "kind": "graphrag_community_report",
                    "community": str(community if community is not None else ""),
                    "level": str(r.get("level") if r.get("level") is not None else ""),
                    "rank": str(r.get("rank") if r.get("rank") is not None else ""),
                },
            )
        )

    return items, documents, len(reports), truncated, MS_GRAPHRAG_STRATEGY
