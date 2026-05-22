"""Workspace baseline reset helpers."""

from __future__ import annotations

from app.workspace_reset import preview_workspace_reset


def test_preview_shape_without_db() -> None:
    """Preview dataclass serializes expected keys."""
    from app.workspace_reset import ResetPreview

    p = ResetPreview(workspace_id="00000000-0000-0000-0000-000000000001", busy=False)
    d = p.to_dict()
    assert d["workspace_id"] == "00000000-0000-0000-0000-000000000001"
    assert d["busy"] is False
    assert "counts" in d


def test_busy_error_type() -> None:
    from app.workspace_reset import WorkspaceResetBusyError

    err = WorkspaceResetBusyError(["1 dream job(s) active"])
    assert "dream" in str(err)
