"""LLM note generation respects max_notes (mocked Cohere client)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.notes_llm import generate_notes_from_episodes


@pytest.mark.asyncio
async def test_respects_max_notes() -> None:
    episodes = [
        {"id": "e1", "text": "hello world " * 50, "page_start": 1, "page_end": 1, "sequence": 0},
    ]

    many_notes = [
        {"title": f"n{i}", "body": "b", "tags": [], "source_chunk_indices": [0]} for i in range(12)
    ]
    payload = json.dumps({"notes": many_notes, "suggested_links": []})

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=payload))]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

    with patch("app.notes_llm.AsyncOpenAI", return_value=mock_client):
        notes, links = await generate_notes_from_episodes(
            api_key="test-key",
            model="m",
            episodes=episodes,
            max_notes=3,
            streaming=False,
        )

    assert len(notes) == 3
    assert links == []


# ---------------------------------------------------------------------------
# BUG-009 — empty / unparseable streaming response must fall back to
# non-streaming instead of raising ``JSONDecodeError`` to the worker.
# ---------------------------------------------------------------------------


async def _async_iter(items: list[object]) -> object:
    """Tiny helper to build an async iterator for streaming-style mocks."""

    class _AsyncIter:
        def __init__(self, items: list[object]) -> None:
            self._items = list(items)

        def __aiter__(self) -> "_AsyncIter":
            return self

        async def __anext__(self) -> object:
            if not self._items:
                raise StopAsyncIteration
            return self._items.pop(0)

    return _AsyncIter(items)


@pytest.mark.asyncio
async def test_empty_streaming_response_falls_back_to_nonstreaming() -> None:
    """When the Cohere stream yields zero content chunks, the function must
    transparently retry without streaming rather than raise JSONDecodeError.

    This is the symptom user reported: "Job failed: JSONDecodeError:
    Expecting value: line 1 column 1 (char 0)".
    """
    episodes = [
        {"id": "e1", "text": "hello world", "page_start": 1, "page_end": 1, "sequence": 0},
    ]
    one_note_payload = json.dumps(
        {"notes": [{"title": "t", "body": "b", "tags": [], "source_chunk_indices": [0]}],
         "suggested_links": []}
    )

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=one_note_payload))]

    mock_client = MagicMock()
    # First call (streaming=True) — return an empty async iterator (no
    # content chunks). Second call (the non-streaming fallback) — return
    # the real payload.
    empty_stream = await _async_iter([])
    mock_client.chat.completions.create = AsyncMock(
        side_effect=[empty_stream, mock_resp]
    )

    with patch("app.notes_llm.AsyncOpenAI", return_value=mock_client):
        notes, _links = await generate_notes_from_episodes(
            api_key="test-key",
            model="m",
            episodes=episodes,
            max_notes=5,
            streaming=True,
        )

    assert [n["title"] for n in notes] == ["t"]
    # Streaming attempt + non-streaming fallback = two calls.
    assert mock_client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_unparseable_streaming_response_falls_back_to_nonstreaming() -> None:
    """If the stream yields non-JSON garbage we still recover by calling
    the non-streaming endpoint, which uses Cohere's batched JSON path.
    """
    episodes = [
        {"id": "e1", "text": "x", "page_start": 1, "page_end": 1, "sequence": 0},
    ]
    good_payload = json.dumps(
        {"notes": [{"title": "ok", "body": "b", "tags": [], "source_chunk_indices": [0]}],
         "suggested_links": []}
    )

    # Streaming yields a single "not json" chunk.
    garbage_chunk = MagicMock()
    garbage_chunk.choices = [MagicMock(delta=MagicMock(content="not json"))]
    bad_stream = await _async_iter([garbage_chunk])

    good_resp = MagicMock()
    good_resp.choices = [MagicMock(message=MagicMock(content=good_payload))]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(
        side_effect=[bad_stream, good_resp]
    )

    with patch("app.notes_llm.AsyncOpenAI", return_value=mock_client):
        notes, _links = await generate_notes_from_episodes(
            api_key="test-key",
            model="m",
            episodes=episodes,
            max_notes=5,
            streaming=True,
        )

    assert [n["title"] for n in notes] == ["ok"]
    assert mock_client.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_both_paths_empty_raises_clear_error() -> None:
    """If even the non-streaming fallback returns empty, we must raise a
    message that mentions Cohere / API key / quota so the operator-facing
    failure_reason is actionable.
    """
    episodes = [
        {"id": "e1", "text": "x", "page_start": 1, "page_end": 1, "sequence": 0},
    ]
    empty_resp = MagicMock()
    empty_resp.choices = [MagicMock(message=MagicMock(content=""))]

    mock_client = MagicMock()
    empty_stream = await _async_iter([])
    mock_client.chat.completions.create = AsyncMock(
        side_effect=[empty_stream, empty_resp]
    )

    with patch("app.notes_llm.AsyncOpenAI", return_value=mock_client):
        with pytest.raises(RuntimeError, match="empty notes response"):
            await generate_notes_from_episodes(
                api_key="test-key",
                model="m",
                episodes=episodes,
                max_notes=5,
                streaming=True,
            )
