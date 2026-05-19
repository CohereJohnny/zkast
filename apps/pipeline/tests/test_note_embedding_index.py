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
