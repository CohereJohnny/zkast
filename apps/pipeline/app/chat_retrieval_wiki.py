"""Wiki retrieval strategy (eval placeholder).

Wiki pages are not yet indexed for retrieval; this returns no grounding so the
eval harness can include a `wiki` column without special-casing it. When real
wiki retrieval lands, replace the body here and flip the registry entry.
"""

from __future__ import annotations

from typing import Any

from app.cohere_chat import ChatDocument


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
    _ = (settings, database_url, workspace_id, query_text, scope, top_k, doc_token_budget)
    return [], [], 0, False, "wiki_stub"
