"""Memory-system adapter helpers."""

from app.eval.adapters import MODE_ALIASES, normalize_mode


def test_mode_aliases() -> None:
    assert normalize_mode("raw") == "rag"
    assert normalize_mode("zettel") == "zettelkasten_notes"
    assert normalize_mode("amem") == "amem_lite"
    assert normalize_mode("graph") == "graph"
