"""Sprint 6 — Cohere v2 chat wrapper for grounded, streaming generation.

This module is the *only* place that talks to Cohere's chat API directly
for the grounded-chat feature. It wraps Cohere's native v2 SDK
(``cohere.AsyncClientV2``) rather than the OpenAI-compat shim because:

* ``documents=[...]`` and the ``citations`` event stream are first-class
  on the v2 endpoint; the compat path requires reverse-engineering Cohere's
  non-standard ``citations`` extension on streamed deltas.
* Graphiti's internal calls keep using ``OpenAIGenericClient`` — this
  module is additive.

Resilience patterns mirror Sprint 5b/5c:

* ``_call_with_retry`` does 3-attempt exponential backoff with jitter for
  the same transient classes that ``cohere_adapters._post_json_with_retry``
  catches.
* Empty-stream fallback (BUG-009 pattern): if the streamed iterator closes
  with zero content deltas, we transparently retry once non-streaming and
  surface a ``warning``-level event to the caller via ``on_warning``.
* The wrapper never depends on ``redis`` or ``job_redis`` directly — the
  caller (``chat_turn.py``) supplies async callbacks for tokens, citations,
  and warnings. That keeps this module unit-testable without a Redis
  fixture.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx
import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class ChatDocument:
    """Grounding document passed to Cohere ``chat`` / ``chat_stream``.

    ``id`` is the stable identifier we control — prefixed with the source
    kind (``note:<uuid>``, ``entity:<uuid>``, ``relationship:<uuid>``,
    ``episode:<uuid>``) so the citation reverse-map in ``chat_turn`` is
    deterministic, not heuristic.
    """

    id: str
    text: str
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_cohere(self) -> dict[str, Any]:
        data: dict[str, Any] = {"text": self.text}
        if self.title:
            data["title"] = self.title
        if self.metadata:
            data.update({k: str(v) for k, v in self.metadata.items() if v is not None})
        return {"id": self.id, "data": data}


@dataclass
class CitationSpan:
    """One finalized citation from a Cohere stream / non-streaming call.

    ``text_start`` / ``text_end`` are character offsets into the assistant's
    response. ``source_ids`` is the list of document ids the citation
    references (using our prefixed scheme).
    """

    text_start: int
    text_end: int
    text: str
    source_ids: list[str]


@dataclass
class ChatStreamResult:
    """Aggregated output of a chat call (streamed or not)."""

    text: str
    citations: list[CitationSpan]
    finish_reason: str | None
    tokens_in: int | None
    tokens_out: int | None
    used_streaming: bool


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------


_TRANSIENT_TYPES: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)

_MAX_ATTEMPTS = 3
_BASE_BACKOFF_S = 1.0

# Cohere's grounded chat returns ``422 NO_VALID_RESPONSE_GENERATED`` when
# the model gives up grounding (e.g. the documents don't contain anything
# relevant to the question). This is a *refusal*, not a transport error —
# we surface it to the caller as a clean ChatStreamResult so the chat
# turn ends with status="refused" instead of a generic exception.
_REFUSAL_ERROR_TYPES = frozenset(
    {
        "NO_VALID_RESPONSE_GENERATED",
        # Reserved: Cohere has shipped policy-style refusal codes under
        # other names historically; add them here as they surface.
    }
)


def _extract_cohere_body(exc: BaseException) -> dict[str, Any] | None:
    """Best-effort pull the JSON ``body`` payload off a Cohere SDK error."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        return body
    if isinstance(body, (bytes, bytearray, str)):
        try:
            import json as _json

            decoded = body.decode() if isinstance(body, (bytes, bytearray)) else body
            parsed = _json.loads(decoded)
            if isinstance(parsed, dict):
                return parsed
        except Exception:  # noqa: BLE001
            return None
    return None


def _is_refusal_error(exc: BaseException) -> bool:
    """True iff ``exc`` is a Cohere 422 with a refusal-style ``error_type``."""
    if type(exc).__name__ != "UnprocessableEntityError":
        return False
    body = _extract_cohere_body(exc)
    if not body:
        return False
    et = str(body.get("error_type") or "").upper()
    return et in _REFUSAL_ERROR_TYPES


def _refusal_result_from_error(exc: BaseException) -> ChatStreamResult:
    """Build a friendly refusal payload from a Cohere policy 422."""
    body = _extract_cohere_body(exc) or {}
    raw_msg = str(body.get("message") or "").strip()
    text = (
        "I couldn't ground an answer from the retrieved context for this "
        "question. Try rephrasing, broadening the session scope, or "
        "switching to a different retrieval strategy."
    )
    if raw_msg:
        text = f"{text}\n\n(model: {raw_msg})"
    return ChatStreamResult(
        text=text,
        citations=[],
        finish_reason="refused",
        tokens_in=None,
        tokens_out=None,
        used_streaming=False,
    )


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, _TRANSIENT_TYPES):
        return True
    # cohere.errors.* — surface as a generic class check so the import is
    # optional. The Cohere SDK raises subclasses of httpx errors plus its
    # own typed errors (``ServiceUnavailableError``, ``GatewayTimeoutError``,
    # ``TooManyRequestsError``) which we treat as transient.
    name = type(exc).__name__
    if name in {
        "ServiceUnavailableError",
        "GatewayTimeoutError",
        "TooManyRequestsError",
        "InternalServerError",
    }:
        return True
    # ``HTTPStatusError`` from httpx — retry only 5xx / 429.
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


async def _call_with_retry(
    op_name: str,
    factory: Callable[[], Awaitable[Any]],
) -> Any:
    """Run an async factory with exponential-backoff retries on transient errors."""

    last_exc: BaseException | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await factory()
        except BaseException as exc:  # noqa: BLE001 — we re-raise non-transient below
            if isinstance(exc, asyncio.CancelledError):
                raise
            if not _is_transient(exc):
                raise
            last_exc = exc
            if attempt >= _MAX_ATTEMPTS:
                break
            backoff = _BASE_BACKOFF_S * (2 ** (attempt - 1))
            backoff *= 0.75 + 0.5 * random.random()
            logger.warning(
                "cohere_chat_transient_retry "
                f"op={op_name} attempt={attempt}/{_MAX_ATTEMPTS} "
                f"backoff={backoff:.2f}s err={type(last_exc).__name__}"
            )
            await asyncio.sleep(backoff)
    assert last_exc is not None
    raise last_exc


# ---------------------------------------------------------------------------
# Citation extraction helpers (Cohere v2 shapes)
# ---------------------------------------------------------------------------


def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``obj[name]`` or ``obj.name`` so we tolerate dict and pydantic shapes."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _extract_source_ids(sources: Any) -> list[str]:
    """From a Cohere citation's ``sources`` array, return the document ids."""
    if not sources:
        return []
    ids: list[str] = []
    for s in sources:
        # Two shapes Cohere has shipped in practice:
        #   { "type": "document", "id": "...", "document": {"id": "...", ...} }
        #   { "type": "document", "document": {"id": "..."} }
        sid = _safe_attr(s, "id")
        if not sid:
            doc = _safe_attr(s, "document")
            sid = _safe_attr(doc, "id")
        if sid:
            ids.append(str(sid))
    return ids


def _build_citation(citation: Any) -> CitationSpan | None:
    """Translate a Cohere citation object into our normalized ``CitationSpan``."""
    start = _safe_attr(citation, "start")
    end = _safe_attr(citation, "end")
    text = _safe_attr(citation, "text", "")
    sources = _safe_attr(citation, "sources", [])
    if start is None or end is None:
        return None
    try:
        start_i = int(start)
        end_i = int(end)
    except (TypeError, ValueError):
        return None
    if end_i <= start_i:
        return None
    return CitationSpan(
        text_start=start_i,
        text_end=end_i,
        text=str(text)[:600],
        source_ids=_extract_source_ids(sources),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


WarningCb = Callable[[str, dict[str, Any] | None], Awaitable[None]]
TokenCb = Callable[[str], Awaitable[None]]
CitationCb = Callable[[CitationSpan], Awaitable[None]]


async def chat_stream_grounded(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    documents: list[ChatDocument],
    on_token: TokenCb,
    on_citation: CitationCb,
    on_warning: WarningCb | None = None,
    temperature: float = 0.2,
    timeout_s: float = 120.0,
) -> ChatStreamResult:
    """Stream a grounded chat completion from Cohere.

    Falls back to a single non-streaming call when the stream yields zero
    content deltas (BUG-009 pattern). All transient errors retry once with
    exponential backoff via :func:`_call_with_retry`.
    """

    # Import the SDK lazily so unit tests can ``patch`` it without paying
    # the import cost.
    import cohere  # type: ignore[import-not-found]

    client = cohere.AsyncClientV2(api_key=api_key, timeout=timeout_s)
    docs_payload = [d.to_cohere() for d in documents]

    # ---- Phase 1: streaming attempt ----
    text_buf: list[str] = []
    citations: list[CitationSpan] = []
    finish_reason: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None

    # NB: ``cohere.AsyncClientV2.chat_stream`` is itself an async generator
    # function (see SDK signature ``-> AsyncIterator[V2ChatStreamResponse]``),
    # so calling it does **not** return a coroutine — it returns the iterator
    # directly. Awaiting it raises ``TypeError: object async_generator can't
    # be used in 'await' expression``. The retry helper handles transient
    # errors *during* iteration below; the function call itself never blocks
    # on the network.
    try:
        stream = client.chat_stream(
            model=model,
            messages=messages,
            documents=docs_payload,
            temperature=temperature,
        )
    except asyncio.CancelledError:
        await _safe_close(client)
        raise
    except BaseException as exc:
        if not _is_transient(exc):
            await _safe_close(client)
            raise
        # Transient error opening the stream — sleep + retry once. The
        # full _call_with_retry ladder is reserved for the non-streaming
        # path where it's safer to redo the whole request.
        logger.warning(
            f"cohere_chat_stream_open_retry err={type(exc).__name__}"
        )
        await asyncio.sleep(_BASE_BACKOFF_S)
        try:
            stream = client.chat_stream(
                model=model,
                messages=messages,
                documents=docs_payload,
                temperature=temperature,
            )
        except BaseException:
            await _safe_close(client)
            raise

    try:
        async for event in stream:
            etype = _safe_attr(event, "type", "")
            if etype == "content-delta":
                delta = _safe_attr(event, "delta")
                message_d = _safe_attr(delta, "message")
                content_d = _safe_attr(message_d, "content")
                text_d = _safe_attr(content_d, "text", "")
                if text_d:
                    text_buf.append(str(text_d))
                    try:
                        await on_token(str(text_d))
                    except Exception:  # noqa: BLE001 — token cb must not poison
                        logger.warning("cohere_chat_on_token_failed", exc_info=True)
            elif etype in ("citation-start", "citation"):
                delta = _safe_attr(event, "delta")
                message_d = _safe_attr(delta, "message")
                # Single citation per event ("citation-start") or array
                # ("citation") — handle both defensively.
                cit_obj = _safe_attr(message_d, "citations")
                if cit_obj is None:
                    cit_obj = _safe_attr(message_d, "citation")
                spans = _build_citations(cit_obj)
                for span in spans:
                    citations.append(span)
                    try:
                        await on_citation(span)
                    except Exception:  # noqa: BLE001
                        logger.warning("cohere_chat_on_citation_failed", exc_info=True)
            elif etype == "message-end":
                delta = _safe_attr(event, "delta")
                finish_reason = _safe_attr(delta, "finish_reason") or finish_reason
                usage = _safe_attr(delta, "usage")
                tokens = _safe_attr(usage, "tokens") or _safe_attr(
                    usage, "billed_units"
                )
                tokens_in = _coerce_int(_safe_attr(tokens, "input_tokens")) or tokens_in
                tokens_out = (
                    _coerce_int(_safe_attr(tokens, "output_tokens")) or tokens_out
                )
    except asyncio.CancelledError:
        await _safe_close(client)
        raise
    except Exception as exc:  # noqa: BLE001
        # Cohere's "I can't ground this" 422 is a refusal, not a failure
        # — surface it as a clean refusal result regardless of whether
        # any partial tokens leaked first.
        if _is_refusal_error(exc):
            logger.info(
                "cohere_chat_stream_refusal "
                f"error_type={(_extract_cohere_body(exc) or {}).get('error_type')}"
            )
            await _safe_close(client)
            if on_warning:
                try:
                    await on_warning(
                        "Model declined to ground a response from retrieved context.",
                        {"reason": "policy_refusal"},
                    )
                except Exception:  # noqa: BLE001
                    pass
            return _refusal_result_from_error(exc)
        # If we got *some* tokens before the stream broke, prefer surfacing
        # the partial result over an exception — but only when we got
        # citations or text. Otherwise re-raise to the caller for the
        # standard error path.
        if not text_buf:
            await _safe_close(client)
            raise
        logger.warning(f"cohere_chat_stream_broke_after_partial error={exc!s}")

    text = "".join(text_buf)

    if text.strip():
        await _safe_close(client)
        return ChatStreamResult(
            text=text,
            citations=citations,
            finish_reason=finish_reason,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            used_streaming=True,
        )

    # ---- Phase 2: empty-stream fallback (BUG-009 pattern) ----
    logger.warning(
        "cohere_chat_empty_stream_fallback_to_nonstreaming "
        f"model={model} documents={len(documents)}"
    )
    if on_warning:
        try:
            await on_warning(
                "Chat LLM stream returned no content; retrying with stream=False",
                {"reason": "empty_stream", "documents": len(documents)},
            )
        except Exception:  # noqa: BLE001
            pass

    async def _call_nonstream() -> Any:
        return await client.chat(
            model=model,
            messages=messages,
            documents=docs_payload,
            temperature=temperature,
        )

    try:
        try:
            resp = await _call_with_retry("chat", _call_nonstream)
        except Exception as exc:  # noqa: BLE001
            # Same refusal handling as the streaming branch — Cohere
            # 422 NO_VALID_RESPONSE_GENERATED is a model-side refusal.
            if _is_refusal_error(exc):
                logger.info(
                    "cohere_chat_nonstream_refusal "
                    f"error_type={(_extract_cohere_body(exc) or {}).get('error_type')}"
                )
                if on_warning:
                    try:
                        await on_warning(
                            "Model declined to ground a response from retrieved context.",
                            {"reason": "policy_refusal"},
                        )
                    except Exception:  # noqa: BLE001
                        pass
                return _refusal_result_from_error(exc)
            raise
    finally:
        await _safe_close(client)

    return _build_nonstream_result(resp)


def _coerce_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _build_citations(raw: Any) -> list[CitationSpan]:
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        items = [raw]
    out: list[CitationSpan] = []
    for c in items:
        span = _build_citation(c)
        if span:
            out.append(span)
    return out


def _build_nonstream_result(resp: Any) -> ChatStreamResult:
    """Translate the non-streaming Cohere v2 ``chat`` response into our shape."""
    message = _safe_attr(resp, "message")
    content_list = _safe_attr(message, "content", []) or []
    text_parts: list[str] = []
    for c in content_list:
        text_parts.append(str(_safe_attr(c, "text", "")))
    text = "".join(text_parts)
    citations_raw = _safe_attr(message, "citations", []) or []
    citations = _build_citations(citations_raw)

    finish_reason = _safe_attr(resp, "finish_reason")
    usage = _safe_attr(resp, "usage")
    tokens = _safe_attr(usage, "tokens") or _safe_attr(usage, "billed_units")
    tokens_in = _coerce_int(_safe_attr(tokens, "input_tokens"))
    tokens_out = _coerce_int(_safe_attr(tokens, "output_tokens"))

    return ChatStreamResult(
        text=text,
        citations=citations,
        finish_reason=str(finish_reason) if finish_reason else None,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        used_streaming=False,
    )


async def _safe_close(client: Any) -> None:
    """Close the async cohere client without raising. Some SDK versions
    expose ``aclose``, others ``close``, others nothing — be permissive."""
    for attr in ("aclose", "close"):
        fn = getattr(client, attr, None)
        if fn is None:
            continue
        try:
            res = fn()
            if hasattr(res, "__await__"):
                await res
            return
        except Exception:  # noqa: BLE001
            return
