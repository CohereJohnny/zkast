"""GraphRAG indexer: settings generation + workspace writing (dep-agnostic)."""

import yaml

from app.graphrag_indexer import (
    DEFAULT_ENTITY_TYPES,
    EMBED_DIM,
    build_graphrag_settings,
    write_workspace,
)


def test_build_settings_all_cohere_1536() -> None:
    s = build_graphrag_settings(
        base_url="https://api.cohere.com/compatibility/v1",
        chat_model="command-a-plus-05-2026",
        embed_model="embed-v4.0",
    )
    chat = s["completion_models"]["default_completion_model"]
    embed = s["embedding_models"]["default_embedding_model"]
    assert chat["api_base"] == "https://api.cohere.com/compatibility/v1"
    assert chat["model"] == "command-a-plus-05-2026"
    assert chat["model_supports_json"] is True
    assert embed["model"] == "embed-v4.0"
    # 1536 standard + float encoding to fix the arrow / dim-mismatch issues.
    assert embed["call_args"]["dimensions"] == EMBED_DIM == 1536
    assert embed["call_args"]["encoding_format"] == "float"
    # cache.type must be json (not file) — graphrag 3.1.0 gotcha.
    assert s["cache"]["type"] == "json"
    assert s["vector_store"]["type"] == "lancedb"
    assert s["extract_graph"]["entity_types"] == DEFAULT_ENTITY_TYPES


def test_build_settings_custom_entity_types_and_dim() -> None:
    s = build_graphrag_settings(
        base_url="https://x/v1",
        chat_model="m",
        embed_model="e",
        entity_types=["person", "org"],
        embed_dim=1024,
    )
    assert s["extract_graph"]["entity_types"] == ["person", "org"]
    assert s["embedding_models"]["default_embedding_model"]["call_args"]["dimensions"] == 1024


def test_write_workspace(tmp_path) -> None:
    settings = build_graphrag_settings(base_url="https://x/v1", chat_model="m", embed_model="e")
    docs = [{"id": "a1", "text": "hello"}, {"id": "b2", "text": "world"}]
    write_workspace(tmp_path, settings, docs)
    assert (tmp_path / "settings.yaml").exists()
    loaded = yaml.safe_load((tmp_path / "settings.yaml").read_text())
    assert loaded["embedding_models"]["default_embedding_model"]["call_args"]["dimensions"] == 1536
    assert (tmp_path / "input" / "a1.txt").read_text() == "hello"
    assert (tmp_path / "input" / "b2.txt").read_text() == "world"
