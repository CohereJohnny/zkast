"""Provider resolution: cohere default, unknown/unconfigured errors."""

from types import SimpleNamespace

import pytest

from app import providers
from app.providers import KNOWN_PROVIDERS, ProviderError, resolve_provider


def _fake_settings() -> SimpleNamespace:
    return SimpleNamespace(
        cohere_api_key="env-cohere-key",
        database_url="postgresql://unused",
        master_encryption_key_bytes=b"0" * 32,
    )


def test_known_providers_registry() -> None:
    assert set(KNOWN_PROVIDERS) == {"cohere_compat", "openai", "azure_openai"}
    assert KNOWN_PROVIDERS["cohere_compat"].supports_rerank is True
    assert KNOWN_PROVIDERS["openai"].supports_rerank is False
    assert KNOWN_PROVIDERS["openai"].api_key_kind == "llm_openai"
    assert KNOWN_PROVIDERS["azure_openai"].base_url_required is True


def test_resolve_unknown_provider_raises() -> None:
    with pytest.raises(ProviderError):
        resolve_provider(_fake_settings(), workspace_id="ws", provider="nope")


def test_resolve_cohere_uses_compat_base(monkeypatch) -> None:
    # Avoid DB: stub pipeline settings; cohere key comes from env (settings).
    monkeypatch.setattr(
        providers,
        "fetch_pipeline_settings",
        lambda *_a, **_k: {"large_model": "command-a", "embed_model": "embed-v4.0"},
    )
    cfg = resolve_provider(_fake_settings(), workspace_id="ws", provider="cohere_compat")
    assert cfg.base_url == providers.COHERE_COMPAT_BASE
    assert cfg.api_key == "env-cohere-key"
    assert cfg.chat_model == "command-a"
    assert cfg.supports_rerank is True


def test_resolve_openai_missing_key_raises(monkeypatch) -> None:
    # No api_keys row -> actionable ProviderError (no probe attempted).
    monkeypatch.setattr(providers, "fetch_api_key_row", lambda *_a, **_k: None)
    with pytest.raises(ProviderError) as ei:
        resolve_provider(_fake_settings(), workspace_id="ws", provider="openai")
    assert "OpenAI" in str(ei.value)
