"""Cohere Embed + Rerank clients implementing Graphiti embedder / cross-encoder slots.

Sprint 5b follow-up: a single transient TLS / connect failure to
``api.cohere.com`` during ``extract_graph`` used to abort
``asyncio.gather`` and burn ~5 minutes of work (BUG-008). These adapters now
retry transient errors with exponential backoff before propagating, and
``extract_graph`` tolerates per-episode failures so one bad apple no longer
spoils the batch.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.embedder.client import EmbedderClient, EmbedderConfig

logger = logging.getLogger(__name__)


# Transient classes — these justify a retry with backoff. Anything else
# (auth errors, 4xx client errors except 429) bubbles up immediately because
# retrying wastes the per-stage timeout budget.
_TRANSIENT_HTTPX_ERRORS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)

# We retry 3 attempts: ~1s, ~2s, ~4s (with ±25% jitter). 7s worst-case is
# well within both arq's per-stage timeout and a single user's patience.
_MAX_ATTEMPTS = 3
_BASE_BACKOFF_S = 1.0


def _is_transient_status(exc: BaseException) -> bool:
    """Return True for HTTP responses that are worth retrying (5xx, 429)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


async def _post_json_with_retry(
    client: httpx.AsyncClient,
    url: str,
    payload: dict[str, Any],
    *,
    label: str,
) -> httpx.Response:
    """POST JSON with exponential-backoff retries on transient errors.

    ``label`` is included in the log line so the operator can see which
    Cohere endpoint failed (embed vs rerank) without scanning the stack
    trace.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = await client.post(url, json=payload)
            # raise_for_status surfaces 4xx/5xx as HTTPStatusError; we only
            # retry the transient subset (5xx + 429) below.
            resp.raise_for_status()
            return resp
        except _TRANSIENT_HTTPX_ERRORS as exc:
            last_exc = exc
        except httpx.HTTPStatusError as exc:
            if not _is_transient_status(exc):
                raise
            last_exc = exc
        if attempt >= _MAX_ATTEMPTS:
            break
        backoff = _BASE_BACKOFF_S * (2 ** (attempt - 1))
        # Add ±25% jitter to avoid thundering herd against the same upstream
        # if many parallel episodes hit a TLS blip simultaneously.
        backoff *= 0.75 + 0.5 * random.random()
        logger.warning(
            "cohere_transient_retry label=%s attempt=%d/%d backoff=%.2fs err=%s",
            label,
            attempt,
            _MAX_ATTEMPTS,
            backoff,
            type(last_exc).__name__,
        )
        await asyncio.sleep(backoff)
    assert last_exc is not None
    raise last_exc


class CohereEmbedder(EmbedderClient):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        embedding_dim: int = 1536,
        timeout_s: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_s
        self.config = EmbedderConfig(embedding_dim=embedding_dim)

    async def create(
        self,
        input_data: str | list[str] | Any,
    ) -> list[float]:
        text = input_data if isinstance(input_data, str) else str(input_data)
        batch = await self.create_batch([text])
        return batch[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(
            base_url="https://api.cohere.com",
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._timeout,
        ) as client:
            resp = await _post_json_with_retry(
                client,
                "/v1/embed",
                {
                    "model": self._model,
                    "texts": input_data_list,
                    "input_type": "search_document",
                },
                label="cohere_embed",
            )
            body = resp.json()
        embeddings = body.get("embeddings") or []
        dim = self.config.embedding_dim
        return [row[:dim] if len(row) >= dim else row for row in embeddings]


class CohereCrossEncoder(CrossEncoderClient):
    def __init__(self, *, api_key: str, model: str, timeout_s: float = 60.0) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_s

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        if not passages:
            return []
        async with httpx.AsyncClient(
            base_url="https://api.cohere.com",
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._timeout,
        ) as client:
            resp = await _post_json_with_retry(
                client,
                "/v1/rerank",
                {
                    "model": self._model,
                    "query": query,
                    "documents": passages,
                },
                label="cohere_rerank",
            )
            body = resp.json()
        results = body.get("results") or []
        ordered = sorted(results, key=lambda r: float(r.get("relevance_score", 0.0)), reverse=True)
        out: list[tuple[str, float]] = []
        for r in ordered:
            idx = int(r["index"])
            score = float(r["relevance_score"])
            if 0 <= idx < len(passages):
                out.append((passages[idx], score))
        return out
