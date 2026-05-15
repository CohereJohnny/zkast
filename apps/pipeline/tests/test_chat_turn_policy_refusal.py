"""Sprint 6b — Cohere policy refusal handling (BUG-014).

When Cohere's grounded chat returns ``422 NO_VALID_RESPONSE_GENERATED`` the
SDK raises ``UnprocessableEntityError``. Historically this bubbled up as a
``failed`` chat turn and the UI rendered the whole HTTP headers dump in the
error panel. The fix is to treat policy-style refusals as a *graceful*
refusal:

- Both the streaming path (when the SDK raises mid-iteration) and the
  non-streaming fallback (when the empty-stream retry hits the same error)
  must convert the exception into a ``ChatStreamResult`` with
  ``finish_reason='refused'``.
- ``on_warning`` fires with a ``policy_refusal`` data hint so the
  JobLogConsole drawer captures the event.
- The user-facing ``text`` is a clean, actionable message — not a JSON
  blob.
- ``tasks._describe_exception`` must surface the parsed ``error_type`` /
  ``message`` rather than the raw ``str(exc)`` for any other code path
  that lets the exception escape.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cohere_chat import ChatDocument, chat_stream_grounded
from app.tasks import _describe_exception


class _RaisingAsyncIter:
    """Async iterator that raises on first ``__anext__``."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def __aiter__(self) -> "_RaisingAsyncIter":
        return self

    async def __anext__(self) -> object:
        raise self._exc


class _EmptyAsyncIter:
    def __aiter__(self) -> "_EmptyAsyncIter":
        return self

    async def __anext__(self) -> object:
        raise StopAsyncIteration


def _make_422(error_type: str = "NO_VALID_RESPONSE_GENERATED") -> Exception:
    """Mirror the Cohere SDK shape: ``UnprocessableEntityError`` with a
    parsed ``body`` dict. The real SDK class has a ``body`` attribute we
    can populate via a simple stub class so the test does not depend on
    the cohere package being importable.
    """

    class UnprocessableEntityError(Exception):
        pass

    exc = UnprocessableEntityError("422")
    exc.body = {  # type: ignore[attr-defined]
        "error_type": error_type,
        "message": "No valid response generated. Try updating messages.",
        "id": "abc",
    }
    return exc


@pytest.mark.asyncio
async def test_streaming_422_converts_to_refusal_result() -> None:
    """A 422 raised mid-stream is converted to a refusal — no exception
    escapes ``chat_stream_grounded`` and ``on_warning`` fires with a
    policy_refusal hint.
    """
    on_warning = AsyncMock()
    on_token = AsyncMock()
    on_citation = AsyncMock()

    mock_client = MagicMock()
    mock_client.chat_stream = MagicMock(
        return_value=_RaisingAsyncIter(_make_422())
    )
    mock_client.chat = AsyncMock()  # must NOT be called
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

    assert result.finish_reason == "refused"
    assert result.used_streaming is False
    assert "ground" in result.text.lower()
    # We should NOT have fallen through to the non-streaming retry — the
    # error was already a final refusal.
    assert mock_client.chat.await_count == 0
    assert on_warning.await_count == 1
    args = on_warning.await_args.args
    assert args[1] is not None and args[1].get("reason") == "policy_refusal"


@pytest.mark.asyncio
async def test_nonstream_fallback_422_converts_to_refusal_result() -> None:
    """The empty-stream fallback path: stream yields nothing, the
    non-streaming ``chat`` call raises a 422
    NO_VALID_RESPONSE_GENERATED, and the wrapper still returns a clean
    refusal payload.
    """
    on_warning = AsyncMock()
    on_token = AsyncMock()
    on_citation = AsyncMock()

    mock_client = MagicMock()
    mock_client.chat_stream = MagicMock(return_value=_EmptyAsyncIter())
    mock_client.chat = AsyncMock(side_effect=_make_422())
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

    # Both the empty-stream warning and the policy_refusal warning fire.
    assert mock_client.chat_stream.call_count == 1
    assert mock_client.chat.await_count == 1
    assert result.finish_reason == "refused"
    assert result.tokens_in is None
    assert result.tokens_out is None

    # At least one of the warnings is a policy_refusal — order matters
    # less than the fact that the drawer sees it.
    reasons = [
        (call.args[1] or {}).get("reason")
        for call in on_warning.await_args_list
    ]
    assert "policy_refusal" in reasons


def test_describe_exception_extracts_cohere_body_fields() -> None:
    """When a Cohere SDK error escapes, ``_describe_exception`` should
    prefer the parsed body's ``error_type`` / ``message`` over
    ``str(exc)`` (which contains the entire HTTP headers blob).
    """
    exc = _make_422()
    text = _describe_exception(exc)
    assert "UnprocessableEntityError" in text
    assert "NO_VALID_RESPONSE_GENERATED" in text
    assert "No valid response generated" in text
    # And critically: no raw header noise.
    assert "access-control" not in text.lower()
    assert "x-debug-trace-id" not in text.lower()


def test_describe_exception_falls_back_to_str_when_no_body() -> None:
    """Non-Cohere exceptions keep the legacy ``Name: msg`` formatting."""

    class FooError(Exception):
        pass

    text = _describe_exception(FooError("kaboom"))
    assert text == "FooError: kaboom"


def test_describe_exception_handles_json_string_body() -> None:
    """Some SDK paths store the body as a JSON string rather than a
    parsed dict — we should still recover the fields.
    """

    class UnprocessableEntityError(Exception):
        pass

    exc = UnprocessableEntityError("422")
    exc.body = (  # type: ignore[attr-defined]
        '{"error_type": "NO_VALID_RESPONSE_GENERATED", "message": "nope"}'
    )
    text = _describe_exception(exc)
    assert "NO_VALID_RESPONSE_GENERATED" in text
    assert "nope" in text
