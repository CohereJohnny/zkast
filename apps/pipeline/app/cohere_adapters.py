"""Cohere Embed + Rerank clients implementing Graphiti embedder / cross-encoder slots."""

from __future__ import annotations

from typing import Any

import httpx

from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.embedder.client import EmbedderClient, EmbedderConfig


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
            resp = await client.post(
                "/v1/embed",
                json={
                    "model": self._model,
                    "texts": input_data_list,
                    "input_type": "search_document",
                },
            )
            resp.raise_for_status()
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
            resp = await client.post(
                "/v1/rerank",
                json={
                    "model": self._model,
                    "query": query,
                    "documents": passages,
                },
            )
            resp.raise_for_status()
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
