"""Pure page-aware text chunking for PDF episodes."""

from __future__ import annotations


def chunk_page_text(page_num: int, text: str | None, max_chars: int) -> list[tuple[str, int, int]]:
    """
    Split a single page's text into one or more chunks.

    Returns tuples of (chunk_text, page_start, page_end) with page_start == page_end == page_num.
    Empty pages yield one empty chunk to preserve provenance.
    """
    raw = text or ""
    stripped = raw.strip()
    if len(stripped) <= max_chars:
        chunk_text = stripped if stripped else ""
        return [(chunk_text, page_num, page_num)]

    parts: list[str] = []
    for para in raw.split("\n\n"):
        p = para.strip()
        if not p:
            continue
        if len(p) <= max_chars:
            parts.append(p)
            continue
        start = 0
        while start < len(p):
            parts.append(p[start : start + max_chars])
            start += max_chars

    if not parts:
        return [("", page_num, page_num)]
    return [(seg, page_num, page_num) for seg in parts]


def assign_sequences(
    chunks: list[tuple[str, int, int]],
    sequence_start: int,
) -> list[tuple[str, int, int, int]]:
    """Attach monotonic sequence numbers starting at sequence_start."""
    out: list[tuple[str, int, int, int]] = []
    seq = sequence_start
    for text, ps, pe in chunks:
        out.append((text, ps, pe, seq))
        seq += 1
    return out
