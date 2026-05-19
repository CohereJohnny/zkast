"""North-history eval mode defaults."""

from __future__ import annotations

from app.eval.runner import NORTH_HISTORY_MODES, default_modes_for_dataset


def test_north_history_default_modes() -> None:
    modes = default_modes_for_dataset("north_history_v1")
    assert modes == NORTH_HISTORY_MODES
    assert "raw_transcript" in modes
    assert "amem_lite" in modes


def test_oil_gas_default_modes() -> None:
    modes = default_modes_for_dataset("oil_gas_v1")
    assert modes == ["rag", "graph", "hybrid"]
