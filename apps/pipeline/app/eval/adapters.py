"""Memory-system adapters for the eval harness.

Each adapter exposes the same ``retrieve`` coroutine used by chat retrieval.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.pipeline_stages.registry import RETRIEVERS, resolve_retriever

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


def retrieval_module(mode: str) -> Any:
    """Resolve a retrieval strategy via the shared stage registry.

    Returns an object with a ``retrieve`` coroutine (the runner calls
    ``retrieval_module(mode).retrieve(...)``). Aliases (raw/zettel/amem) are
    normalized first; unknown modes raise, matching prior eval behavior.
    """
    m = normalize_mode(mode)
    if m not in RETRIEVERS:
        raise ValueError(f"unknown retrieval mode: {mode!r}")
    return SimpleNamespace(retrieve=resolve_retriever(m))
