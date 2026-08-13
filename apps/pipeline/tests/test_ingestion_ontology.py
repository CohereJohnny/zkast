"""Document-level ontology selection on ingestion runs."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.documents_repo import fetch_ingestion_run_ontology
from app.internal_ingestion import _resolve_upload_ontology
from app.prompt_sets_repo import BUILTIN_NAME, BUILTIN_VERSION


def test_resolve_upload_ontology_defaults_to_builtin() -> None:
    with patch("app.internal_ingestion.fetch_prompt_set_row", return_value=None):
        name, version = _resolve_upload_ontology(
            "postgresql://unused",
            workspace_id="00000000-0000-0000-0000-000000000001",
            ontology_name=None,
            ontology_version=None,
        )
    assert (name, version) == (BUILTIN_NAME, BUILTIN_VERSION)


def test_resolve_upload_ontology_rejects_unknown() -> None:
    from fastapi import HTTPException

    with patch("app.internal_ingestion.fetch_prompt_set_row", return_value=None):
        with pytest.raises(HTTPException) as exc:
            _resolve_upload_ontology(
                "postgresql://unused",
                workspace_id="00000000-0000-0000-0000-000000000001",
                ontology_name="healthcare-rcm",
                ontology_version="v2",
            )
    assert exc.value.status_code == 400


def test_resolve_upload_ontology_accepts_known() -> None:
    with patch(
        "app.internal_ingestion.fetch_prompt_set_row",
        return_value={"name": "healthcare-rcm", "version": "v2"},
    ):
        name, version = _resolve_upload_ontology(
            "postgresql://unused",
            workspace_id="00000000-0000-0000-0000-000000000001",
            ontology_name="healthcare-rcm",
            ontology_version="v2",
        )
    assert (name, version) == ("healthcare-rcm", "v2")


def test_fetch_ingestion_run_ontology_defaults_when_missing() -> None:
    with patch("app.documents_repo.psycopg.connect") as connect:
        conn = connect.return_value.__enter__.return_value
        conn.execute.return_value.fetchone.return_value = None
        assert fetch_ingestion_run_ontology(
            "postgresql://unused", ingestion_run_id="00000000-0000-0000-0000-000000000099"
        ) == ("generic", "v1")


def test_extract_graph_resolves_ontology_from_run() -> None:
    """Source contract: extract_graph loads ontology from the ingestion run."""
    from pathlib import Path

    text = Path(__file__).resolve().parents[1].joinpath("app/tasks.py").read_text()
    assert "fetch_ingestion_run_ontology" in text
    assert "resolve_ontology" in text
    assert "ontology_entity_types" in text
    assert "entity_types=ontology_entity_types" in text
