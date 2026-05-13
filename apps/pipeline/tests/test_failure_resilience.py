"""BUG-008 regressions — graph extraction must tolerate transient errors.

Three things this file pins:

1. ``_describe_exception`` never returns an empty string, so the UI's
   "Job failed:" text always has a message after the colon.
2. ``cohere_adapters._post_json_with_retry`` retries transient HTTPX
   errors with exponential backoff and gives up after ``_MAX_ATTEMPTS``.
3. ``_is_transient_status`` retries 5xx + 429 but bubbles 4xx (auth,
   validation, etc.) immediately so we don't burn budget retrying a
   permanent client error.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app import cohere_adapters
from app.tasks import _describe_exception


# ---------------------------------------------------------------------------
# 1. _describe_exception
# ---------------------------------------------------------------------------


def test_describe_exception_empty_message_falls_back_to_type_name() -> None:
    """``httpx.ConnectError()`` has no message; the UI used to show "Job
    failed:" with nothing after. The fallback must include the exception
    type name so the operator has something to grep for.
    """
    exc = httpx.ConnectError("")
    assert _describe_exception(exc) == "ConnectError"


def test_describe_exception_with_message_includes_both() -> None:
    exc = RuntimeError("upstream unavailable")
    assert _describe_exception(exc) == "RuntimeError: upstream unavailable"


def test_describe_exception_truncates_to_max_len() -> None:
    exc = ValueError("x" * 600)
    out = _describe_exception(exc, max_len=120)
    assert len(out) == 120
    assert out.startswith("ValueError: ")


# ---------------------------------------------------------------------------
# 2. cohere_adapters._post_json_with_retry
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Don't actually wait between retry attempts in unit tests."""
    async def _sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(cohere_adapters.asyncio, "sleep", _sleep)


def _fake_response(status_code: int = 200, body: dict[str, Any] | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.request = MagicMock(spec=httpx.Request)
    if status_code >= 400:
        err = httpx.HTTPStatusError(
            "boom", request=resp.request, response=resp
        )
        resp.raise_for_status.side_effect = err
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = body or {}
    return resp


def test_retry_succeeds_after_one_transient_failure() -> None:
    client = MagicMock(spec=httpx.AsyncClient)
    happy = _fake_response(200, {"ok": True})
    client.post = AsyncMock(
        side_effect=[httpx.ConnectError(""), happy],
    )

    out = asyncio.run(
        cohere_adapters._post_json_with_retry(
            client, "/v1/embed", {"x": 1}, label="cohere_embed"
        )
    )

    assert out is happy
    assert client.post.await_count == 2


def test_retry_gives_up_after_max_attempts() -> None:
    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(side_effect=httpx.ConnectError(""))

    with pytest.raises(httpx.ConnectError):
        asyncio.run(
            cohere_adapters._post_json_with_retry(
                client, "/v1/embed", {"x": 1}, label="cohere_embed"
            )
        )

    assert client.post.await_count == cohere_adapters._MAX_ATTEMPTS


def test_retry_bubbles_permanent_4xx_immediately() -> None:
    """A 400 ``invalid 'json_schema'`` from Cohere is permanent — retrying
    just burns budget. Only 5xx + 429 should retry.
    """
    client = MagicMock(spec=httpx.AsyncClient)
    bad = _fake_response(400)
    client.post = AsyncMock(return_value=bad)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(
            cohere_adapters._post_json_with_retry(
                client, "/v1/embed", {"x": 1}, label="cohere_embed"
            )
        )

    assert client.post.await_count == 1


def test_retry_does_retry_5xx() -> None:
    client = MagicMock(spec=httpx.AsyncClient)
    bad = _fake_response(503)
    happy = _fake_response(200, {"ok": True})
    client.post = AsyncMock(side_effect=[bad, happy])

    out = asyncio.run(
        cohere_adapters._post_json_with_retry(
            client, "/v1/rerank", {"x": 1}, label="cohere_rerank"
        )
    )

    assert out is happy
    assert client.post.await_count == 2


def test_retry_does_retry_429_rate_limit() -> None:
    client = MagicMock(spec=httpx.AsyncClient)
    rate_limited = _fake_response(429)
    happy = _fake_response(200, {"ok": True})
    client.post = AsyncMock(side_effect=[rate_limited, happy])

    out = asyncio.run(
        cohere_adapters._post_json_with_retry(
            client, "/v1/embed", {"x": 1}, label="cohere_embed"
        )
    )

    assert out is happy
    assert client.post.await_count == 2
