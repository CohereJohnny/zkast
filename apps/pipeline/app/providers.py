"""Configurable LLM provider abstraction (OpenAI-compatible).

Resolves a provider id to an OpenAI-compatible client config (base_url, api_key,
models). Cohere's compatibility endpoint is the default; OpenAI and Azure/OpenAI
(or any OpenAI-compatible endpoint) are optional bring-your-own-credential
providers stored as ``api_keys`` rows (kind ``llm_<provider>``), with non-secret
config (base_url, model overrides) in the row's ``metadata`` JSON.

This governs *per-configuration* model calls (e.g. the MS GraphRAG plugin and
the auto-tune call); it does not change the built-in Graphiti pipeline, which
stays on Cohere (rerank + embed dims are Cohere-specific).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings
from app.graphiti_factory import COHERE_COMPAT_BASE, resolve_cohere_api_key
from app.secrets import decrypt
from app.workspace_repo import fetch_api_key_row, fetch_pipeline_settings


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    default_base_url: str | None
    default_chat_model: str
    default_embed_model: str
    supports_rerank: bool
    api_key_kind: str | None  # api_keys.kind holding the secret (None = uses Cohere resolution)
    base_url_required: bool = False  # Azure-style: caller must supply base_url in metadata


# Registry of recognized providers. ``cohere_compat`` is the built-in default.
KNOWN_PROVIDERS: dict[str, ProviderSpec] = {
    "cohere_compat": ProviderSpec(
        id="cohere_compat",
        label="Cohere (OpenAI-compatible)",
        default_base_url=COHERE_COMPAT_BASE,
        default_chat_model="command-a-plus-05-2026",
        default_embed_model="embed-v4.0",
        supports_rerank=True,
        api_key_kind=None,
    ),
    "openai": ProviderSpec(
        id="openai",
        label="OpenAI",
        default_base_url="https://api.openai.com/v1",
        default_chat_model="gpt-4o-mini",
        default_embed_model="text-embedding-3-small",
        supports_rerank=False,
        api_key_kind="llm_openai",
    ),
    "azure_openai": ProviderSpec(
        id="azure_openai",
        label="Azure OpenAI (compatible endpoint)",
        default_base_url=None,
        default_chat_model="gpt-4o-mini",
        default_embed_model="text-embedding-3-small",
        supports_rerank=False,
        api_key_kind="llm_azure_openai",
        base_url_required=True,
    ),
}


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    base_url: str
    api_key: str
    chat_model: str
    embed_model: str
    supports_rerank: bool


class ProviderError(Exception):
    """Raised when a provider can't be resolved (missing key/base_url/etc.)."""


def resolve_provider(
    settings: Settings, *, workspace_id: str, provider: str
) -> ProviderConfig:
    """Resolve a provider id to a usable OpenAI-compatible config.

    Raises ProviderError with an actionable message when credentials or required
    config are missing.
    """
    spec = KNOWN_PROVIDERS.get((provider or "").strip().lower())
    if spec is None:
        raise ProviderError(f"Unknown provider {provider!r}")

    if spec.id == "cohere_compat":
        key = resolve_cohere_api_key(settings, workspace_id)
        if not key:
            raise ProviderError("No Cohere API key configured for this workspace")
        pipe = fetch_pipeline_settings(settings.database_url, workspace_id)
        return ProviderConfig(
            provider=spec.id,
            base_url=COHERE_COMPAT_BASE,
            api_key=key,
            chat_model=str(pipe.get("large_model") or spec.default_chat_model),
            embed_model=str(pipe.get("embed_model") or spec.default_embed_model),
            supports_rerank=True,
        )

    assert spec.api_key_kind is not None
    row = fetch_api_key_row(settings.database_url, workspace_id, spec.api_key_kind)
    if not row:
        raise ProviderError(
            f"No {spec.label} API key configured (add an '{spec.api_key_kind}' key in Settings)"
        )
    api_key = decrypt(settings.master_encryption_key_bytes, row["encrypted_secret"]).decode("utf-8")
    meta: dict[str, Any] = row.get("metadata") or {}
    base_url = str(meta.get("base_url") or spec.default_base_url or "").strip()
    if not base_url:
        raise ProviderError(f"{spec.label} requires a base_url in its key metadata")
    return ProviderConfig(
        provider=spec.id,
        base_url=base_url,
        api_key=api_key,
        chat_model=str(meta.get("chat_model") or spec.default_chat_model),
        embed_model=str(meta.get("embed_model") or spec.default_embed_model),
        supports_rerank=spec.supports_rerank,
    )


async def probe_provider_async(cfg: ProviderConfig, *, timeout_s: float = 30.0) -> tuple[bool, str | None, str | None]:
    """Minimal chat + embed probe. Returns (ok, error, stage)."""
    client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=timeout_s, max_retries=0)
    try:
        await client.chat.completions.create(
            model=cfg.chat_model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc), "chat"
    try:
        await client.embeddings.create(model=cfg.embed_model, input="ping")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc), "embed"
    return True, None, None
