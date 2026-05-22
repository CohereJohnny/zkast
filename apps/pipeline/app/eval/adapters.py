"""Memory-system adapters for the eval harness.

Each adapter exposes the same ``retrieve`` coroutine used by chat retrieval.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app import (
    chat_retrieval_graph,
    chat_retrieval_hybrid,
    chat_retrieval_raw,
)
from app.chat_retrieval_notes_vector import retrieve_amem, retrieve_zettel

# Retrieval mode string -> memory-system label persisted on eval results.
MEMORY_SYSTEM_BY_MODE: dict[str, str] = {
    "rag": "raw",
    "raw_transcript": "raw",
    "zettelkasten_notes": "zettel",
    "zettelkasten": "zettel",
    "amem_lite": "amem",
    "amem": "amem",
    "graph": "graph",
    "hybrid": "hybrid",
    "wiki": "wiki",
}

# UI / API aliases -> retrieval mode.
MODE_ALIASES: dict[str, str] = {
    "raw": "rag",
    "zettel": "zettelkasten_notes",
    "amem": "amem_lite",
}


def normalize_mode(mode: str) -> str:
    m = (mode or "").strip().lower()
    return MODE_ALIASES.get(m, m)


def memory_system_for_mode(mode: str) -> str:
    return MEMORY_SYSTEM_BY_MODE.get(normalize_mode(mode), normalize_mode(mode))


async def _wiki_retrieve_empty(
    _settings: Any,
    _database_url: str,
    *,
    workspace_id: str,
    query_text: str,
    scope: dict[str, Any],
    top_k: int,
    doc_token_budget: int,
) -> tuple[list[Any], list[Any], int, bool, str]:
    """Placeholder until wiki pages are indexed for retrieval."""
    _ = (workspace_id, query_text, scope, top_k, doc_token_budget)
    return [], [], 0, False, "wiki_stub"


def retrieval_module(mode: str) -> Any:
    m = normalize_mode(mode)
    if m in ("rag", "raw_transcript"):
        return chat_retrieval_raw
    if m == "graph":
        return chat_retrieval_graph
    if m == "hybrid":
        return chat_retrieval_hybrid
    if m in ("zettelkasten_notes", "zettelkasten"):
        return SimpleNamespace(retrieve=retrieve_zettel)
    if m in ("amem_lite", "amem"):
        return SimpleNamespace(retrieve=retrieve_amem)
    if m == "wiki":
        return SimpleNamespace(retrieve=_wiki_retrieve_empty)
    raise ValueError(f"unknown retrieval mode: {mode!r}")
