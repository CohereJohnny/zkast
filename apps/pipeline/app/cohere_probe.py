"""Lightweight Cohere connectivity checks (chat compat + native embed + rerank)."""

from __future__ import annotations

from typing import Literal

import httpx


async def probe_cohere_async(
    api_key: str,
    *,
    chat_model: str,
    embed_model: str,
    rerank_model: str,
    timeout_s: float = 15.0,
) -> tuple[bool, str | None, Literal["chat", "embed", "rerank"] | None]:
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        try:
            r_chat = await client.post(
                "https://api.cohere.com/compatibility/v1/chat/completions",
                headers=headers,
                json={
                    "model": chat_model,
                    "messages": [
                        {"role": "user", "content": 'Reply with JSON: {"ok": true}'},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 64,
                },
            )
            r_chat.raise_for_status()
        except Exception as exc:  # noqa: BLE001 — probe aggregates
            return False, str(exc)[:300], "chat"

        try:
            r_emb = await client.post(
                "https://api.cohere.com/v1/embed",
                headers=headers,
                json={
                    "model": embed_model,
                    "texts": ["zkast connectivity probe"],
                    "input_type": "search_query",
                },
            )
            r_emb.raise_for_status()
            emb_body = r_emb.json()
            vecs = emb_body.get("embeddings") or []
            if not vecs:
                return False, "embed response missing embeddings", "embed"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:300], "embed"

        try:
            r_rr = await client.post(
                "https://api.cohere.com/v1/rerank",
                headers=headers,
                json={
                    "model": rerank_model,
                    "query": "probe",
                    "documents": ["alpha", "beta"],
                },
            )
            r_rr.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:300], "rerank"

    return True, None, None


def probe_cohere_sync(
    api_key: str,
    *,
    chat_model: str,
    embed_model: str,
    rerank_model: str,
    timeout_s: float = 8.0,
) -> tuple[bool, str | None]:
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(timeout=timeout_s) as client:
            r_chat = client.post(
                "https://api.cohere.com/compatibility/v1/chat/completions",
                headers=headers,
                json={
                    "model": chat_model,
                    "messages": [
                        {"role": "user", "content": 'Reply with JSON: {"ok": true}'},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 64,
                },
            )
            r_chat.raise_for_status()

            r_emb = client.post(
                "https://api.cohere.com/v1/embed",
                headers=headers,
                json={
                    "model": embed_model,
                    "texts": ["zkast readiness probe"],
                    "input_type": "search_query",
                },
            )
            r_emb.raise_for_status()
            emb_body = r_emb.json()
            if not emb_body.get("embeddings"):
                return False, "embed response missing embeddings"

            r_rr = client.post(
                "https://api.cohere.com/v1/rerank",
                headers=headers,
                json={
                    "model": rerank_model,
                    "query": "probe",
                    "documents": ["alpha", "beta"],
                },
            )
            r_rr.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:300]
    return True, None
