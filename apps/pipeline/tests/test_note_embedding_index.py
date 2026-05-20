"""Note embedding index helpers."""

from __future__ import annotations

from app.note_embedding_index import _amem_text, _note_has_amem_fields, _zettel_text


def test_zettel_text_uses_title_and_body() -> None:
    t = _zettel_text({"title": "T", "body": "B"})
    assert "T" in t and "B" in t


def test_amem_text_includes_context_and_keywords() -> None:
    t = _amem_text(
        {
            "title": "T",
            "body": "B",
            "memory_context": "One line context.",
            "memory_keywords": ["alpha", "beta"],
        }
    )
    assert "memory_context:" in t
    assert "memory_keywords:" in t
    assert "alpha" in t


def test_note_has_amem_fields() -> None:
    assert _note_has_amem_fields({"memory_keywords": ["x"]}) is True
    assert _note_has_amem_fields({"memory_context": "ctx"}) is True
    assert _note_has_amem_fields({}) is False


def test_amem_upsert_uses_on_conflict_unique_key(monkeypatch) -> None:
    """Second upsert for same note must call upsert_embedding, not duplicate rows."""
    from unittest.mock import MagicMock

    from app import note_embedding_index as nei

    calls: list[str] = []

    def fake_upsert(_db, **kwargs):
        calls.append(kwargs["source_id"])
        return "row-id"

    def fake_fetch(*_a, **_k):
        return {
            "id": "note-1",
            "title": "T",
            "body": "B",
            "memory_context": "ctx",
            "memory_keywords": ["k"],
        }

    async def fake_embed_batch(texts):
        return [[0.1] * 4 for _ in texts]

    monkeypatch.setattr(nei, "fetch_note", fake_fetch)
    monkeypatch.setattr(nei, "upsert_embedding", fake_upsert)
    monkeypatch.setattr(
        nei,
        "CohereEmbedder",
        lambda **_: MagicMock(create_batch=fake_embed_batch),
    )

    import asyncio

    async def run_twice() -> None:
        await nei.upsert_amem_embeddings_for_notes(
            api_key="k",
            database_url="db",
            workspace_id="ws",
            note_ids=["note-1"],
            agent_id="agent",
            embed_model="embed-v4.0",
        )
        await nei.upsert_amem_embeddings_for_notes(
            api_key="k",
            database_url="db",
            workspace_id="ws",
            note_ids=["note-1"],
            agent_id="agent",
            embed_model="embed-v4.0",
        )

    asyncio.run(run_twice())
    assert calls == ["note-1", "note-1"]
