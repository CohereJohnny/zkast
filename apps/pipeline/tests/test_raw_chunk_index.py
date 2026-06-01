"""Raw-chunk index episode selection."""

import inspect

from app import raw_chunk_index


def test_list_raw_chunks_includes_north_episode_kinds() -> None:
    source = inspect.getsource(raw_chunk_index._list_raw_chunks)
    assert "north_message" in source
    assert "north_turn_window" in source
    assert "pdf_chunk" in source
