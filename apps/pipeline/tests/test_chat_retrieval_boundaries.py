"""Sprint 6b — retrieval-mode boundary tests.

These are the *contract* tests for the GraphRAG-vs-Naive-RAG eval.
The whole eval becomes dishonest if Naive RAG accidentally leans on
zettelkasten / graph artifacts, so the tests below pin two things:

1. The dispatcher in ``chat_turn._retrieve`` routes each mode to the
   matching strategy module and returns the strategy string back to
   the caller.
2. ``chat_retrieval_raw`` (Naive RAG) only queries the raw-chunk
   index. It must not import or call ``graphiti_for_workspace``,
   ``summarize_workspace_graph``, ``filter_options_repo``, or any
   atomic-note / entity / relationship repo.

The boundary check is a static-source scan (cheap, deterministic,
catches refactor drift) plus an in-process dispatch test that uses
fakes for each strategy module.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app import chat_turn


_RAW_RAG_FILE = (
    Path(__file__).parent.parent / "app" / "chat_retrieval_raw.py"
)


def test_naive_rag_source_does_not_import_graph_artifacts() -> None:
    """Static scan: Naive RAG must not import any graph / zettelkasten
    repo or helper. We check imports and call sites only; the module
    docstring is allowed to *describe* the rule and may mention the
    forbidden names.
    """
    src = _RAW_RAG_FILE.read_text()
    # Strip the leading module docstring so the check focuses on code.
    code = src
    if code.startswith('"""'):
        end = code.find('"""', 3)
        if end != -1:
            code = code[end + 3 :]
    # NB: ``from app.graphiti_factory import resolve_cohere_api_key`` is
    # explicitly allowed — the helper only decrypts the workspace's
    # Cohere key and is not graph-aware. The forbidden symbols below
    # are the graph-aware ones.
    forbidden_imports = [
        "from app.notes_repo",
        "from app.entities_repo",
        "from app.filter_options_repo",
        "import app.notes_repo",
        "import app.entities_repo",
        "import app.filter_options_repo",
    ]
    for needle in forbidden_imports:
        assert needle not in code, (
            f"chat_retrieval_raw.py must not contain {needle!r}; "
            "Naive RAG is the control arm and may only see raw chunks."
        )
    forbidden_calls = [
        "graphiti_for_workspace(",
        "summarize_workspace_graph(",
        "filter_options_repo.",
        "entities_repo.",
        "notes_repo.",
    ]
    for needle in forbidden_calls:
        assert needle not in code, (
            f"chat_retrieval_raw.py must not call {needle!r}; "
            "Naive RAG is the control arm and may only see raw chunks."
        )


def test_naive_rag_uses_raw_chunk_index_kind() -> None:
    src = _RAW_RAG_FILE.read_text()
    assert "INDEX_KIND_RAW_CHUNK" in src, (
        "Naive RAG must filter on INDEX_KIND_RAW_CHUNK so it never "
        "leaks rows of any other kind from the embedding index."
    )


def test_dispatcher_routes_rag_to_raw_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_retrieve`` should call the raw strategy when mode='rag' and
    propagate the strategy string back."""
    captured: dict[str, Any] = {}

    async def fake_retrieve(_settings, _db, **kw):
        captured["mode"] = "rag"
        captured["kw"] = kw
        return [], [], 0, False, "rag_raw_chunk_v1"

    monkeypatch.setattr(
        chat_turn, "_retrieve_raw_for_test", fake_retrieve, raising=False
    )

    # Patch the strategy module dispatcher used internally.
    from app import chat_retrieval_raw

    monkeypatch.setattr(chat_retrieval_raw, "retrieve", fake_retrieve)

    result = asyncio.run(
        chat_turn._retrieve(
            settings=SimpleNamespace(),
            database_url="postgresql://stub/none",
            workspace_id="ws",
            query_text="hi",
            scope={},
            top_k=5,
            doc_token_budget=1000,
            retrieval_mode="rag",
        )
    )
    assert captured["mode"] == "rag"
    assert result[-1] == "rag_raw_chunk_v1"


def test_dispatcher_routes_graph_to_graph_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import chat_retrieval_graph

    async def fake_retrieve(_settings, _db, **kw):
        return [], [], 0, False, "graph_graphiti_context_v1"

    monkeypatch.setattr(chat_retrieval_graph, "retrieve", fake_retrieve)

    result = asyncio.run(
        chat_turn._retrieve(
            settings=SimpleNamespace(),
            database_url="postgresql://stub/none",
            workspace_id="ws",
            query_text="hi",
            scope={},
            top_k=5,
            doc_token_budget=1000,
            retrieval_mode="graph",
        )
    )
    assert result[-1] == "graph_graphiti_context_v1"


def test_dispatcher_routes_hybrid_to_hybrid_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import chat_retrieval_hybrid

    async def fake_retrieve(_settings, _db, **kw):
        return [], [], 0, False, "hybrid_typed_entity_v1"

    monkeypatch.setattr(chat_retrieval_hybrid, "retrieve", fake_retrieve)

    result = asyncio.run(
        chat_turn._retrieve(
            settings=SimpleNamespace(),
            database_url="postgresql://stub/none",
            workspace_id="ws",
            query_text="hi",
            scope={},
            top_k=5,
            doc_token_budget=1000,
            retrieval_mode="hybrid",
        )
    )
    assert result[-1] == "hybrid_typed_entity_v1"


def test_dispatcher_falls_back_to_graph_on_unknown_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import chat_retrieval_graph

    async def fake_retrieve(_settings, _db, **kw):
        return [], [], 0, False, "graph_graphiti_context_v1"

    monkeypatch.setattr(chat_retrieval_graph, "retrieve", fake_retrieve)

    result = asyncio.run(
        chat_turn._retrieve(
            settings=SimpleNamespace(),
            database_url="postgresql://stub/none",
            workspace_id="ws",
            query_text="hi",
            scope={},
            top_k=5,
            doc_token_budget=1000,
            retrieval_mode="bogus_mode",
        )
    )
    assert result[-1] == "graph_graphiti_context_v1"
