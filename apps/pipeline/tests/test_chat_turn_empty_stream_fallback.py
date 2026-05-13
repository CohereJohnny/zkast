"""Sprint 6 — empty-stream fallback (BUG-009 pattern).

When Cohere's streaming endpoint yields zero ``content-delta`` events,
``cohere_chat.chat_stream_grounded`` must:

1. Retry once with the non-streaming ``chat`` endpoint.
2. Surface a ``warning`` event to the supplied ``on_warning`` callback so
   the JobLogConsole drawer can show the user what happened.
3. Still return a populated ``ChatStreamResult`` from the non-streaming
   path (with ``used_streaming=False``).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cohere_chat import ChatDocument, chat_stream_grounded


class _EmptyAsyncIter:
    """Async iterator that yields no events — simulates the empty stream."""

    def __aiter__(self) -> "_EmptyAsyncIter":
        return self

    async def __anext__(self) -> object:
        raise StopAsyncIteration


@pytest.mark.asyncio
async def test_empty_stream_falls_back_to_nonstreaming_and_warns() -> None:
    """The wrapper must:
    - call chat_stream first
    - detect 0 content deltas
    - emit a warning callback
    - retry via chat (non-streaming)
    - return the result from the non-streaming response.
    """
    on_warning = AsyncMock()
    on_token = AsyncMock()
    on_citation = AsyncMock()

    # Build the non-streaming response shape (Cohere v2 chat).
    nonstream_resp = SimpleNamespace(
        message=SimpleNamespace(
            content=[SimpleNamespace(text="Fallback response.")],
            citations=[],
        ),
        finish_reason="COMPLETE",
        usage=SimpleNamespace(
            tokens=SimpleNamespace(input_tokens=10, output_tokens=3)
        ),
    )

    mock_client = MagicMock()
    # BUG-012 contract: cohere.AsyncClientV2.chat_stream is an async-generator
    # function, NOT a coroutine function — calling it returns the iterator
    # synchronously. Mocking with ``AsyncMock`` would force callers to
    # ``await`` the result, masking the production bug. ``MagicMock`` with
    # ``return_value`` mimics the real Cohere behaviour.
    mock_client.chat_stream = MagicMock(return_value=_EmptyAsyncIter())
    mock_client.chat = AsyncMock(return_value=nonstream_resp)
    mock_client.aclose = AsyncMock()

    fake_cohere = MagicMock()
    fake_cohere.AsyncClientV2 = MagicMock(return_value=mock_client)

    with patch.dict("sys.modules", {"cohere": fake_cohere}):
        result = await chat_stream_grounded(
            api_key="test-key",
            model="command-a-plus-05-2026",
            messages=[{"role": "user", "content": "hi"}],
            documents=[ChatDocument(id="note:1", text="hi")],
            on_token=on_token,
            on_citation=on_citation,
            on_warning=on_warning,
        )

    # Both paths invoked, in order. ``chat_stream`` is a sync call that
    # returns an async iterator (BUG-012 contract — see MagicMock wiring
    # above), so we assert ``call_count`` not ``await_count``. ``chat``
    # really is a coroutine function so it keeps ``await_count``.
    assert mock_client.chat_stream.call_count == 1
    assert mock_client.chat.await_count == 1

    # Warning callback fired exactly once with an `empty_stream` data hint.
    assert on_warning.await_count == 1
    args = on_warning.await_args.args
    assert "empty" in args[0].lower() or "stream" in args[0].lower()
    assert args[1] is None or args[1].get("reason") == "empty_stream"

    # Non-streaming result surfaced.
    assert result.text == "Fallback response."
    assert result.tokens_in == 10
    assert result.tokens_out == 3
    assert result.used_streaming is False
    # And no spurious token callbacks fired during the empty stream.
    assert on_token.await_count == 0
