"""Unit tests for page-aware chunking."""

from __future__ import annotations

from app.chunking import assign_sequences, chunk_page_text


def test_chunk_single_short_page() -> None:
    chunks = chunk_page_text(1, "Hello world", max_chars=100)
    assert chunks == [("Hello world", 1, 1)]


def test_chunk_empty_page() -> None:
    chunks = chunk_page_text(3, "", max_chars=50)
    assert chunks == [("", 3, 3)]


def test_chunk_whitespace_only_short() -> None:
    chunks = chunk_page_text(2, "   \n\t  ", max_chars=10)
    assert chunks == [("", 2, 2)]


def test_chunk_splits_oversized_paragraphs() -> None:
    text = "a" * 50 + "\n\n" + "b" * 120
    chunks = chunk_page_text(4, text, max_chars=40)
    assert all(e[1] == e[2] == 4 for e in chunks)
    joined = "".join(c[0] for c in chunks)
    assert "a" * 50 in joined
    assert "b" * 120 in joined


def test_assign_sequences_monotonic() -> None:
    chunks = [("a", 1, 1), ("b", 1, 1), ("c", 2, 2)]
    with_seq = assign_sequences(chunks, sequence_start=0)
    assert [x[3] for x in with_seq] == [0, 1, 2]
    with_seq2 = assign_sequences(chunks, sequence_start=10)
    assert [x[3] for x in with_seq2] == [10, 11, 12]
