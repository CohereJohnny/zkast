"""Sprint 5c — typed entity extraction via Graphiti.

Locks in the contract that ``extract_graph`` passes our Pydantic entity
schemas + edge schemas to ``graphiti.add_episode``. Without these,
Graphiti's default extractor labels every entity as the generic
``Entity``, and `entities_repo.entity_type_from_labels` collapses
everything into the residual ``"Concept"`` bucket — which is exactly
the visual bug we shipped Sprint 5c to fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from app import entity_schemas


def test_entity_types_present_for_each_named_type() -> None:
    expected = {
        "Person",
        "Organization",
        "Location",
        "Document",
        "Standard",
        "Equipment",
        "Process",
        "Material",
        "Event",
        "Concept",
    }
    assert set(entity_schemas.ENTITY_TYPES.keys()) == expected


def test_every_entity_type_is_a_pydantic_model() -> None:
    for name, cls in entity_schemas.ENTITY_TYPES.items():
        assert isinstance(cls, type) and issubclass(cls, BaseModel), (
            f"entity_types[{name!r}] = {cls!r} is not a Pydantic BaseModel; "
            "Graphiti's add_episode() will reject it."
        )


def test_entity_type_descriptions_are_nonempty() -> None:
    for name, cls in entity_schemas.ENTITY_TYPES.items():
        assert (cls.__doc__ or "").strip(), f"{name} missing docstring"


def test_entity_types_have_required_fields() -> None:
    for name, cls in entity_schemas.ENTITY_TYPES.items():
        fields = cls.model_fields
        assert fields, f"{name} has no fields"
        required = [k for k, f in fields.items() if f.is_required()]
        assert required, f"{name} must have at least one required field"


def test_standard_requires_identifier() -> None:
    Standard = entity_schemas.ENTITY_TYPES["Standard"]
    with pytest.raises(Exception):
        Standard()  # type: ignore[call-arg]
    inst = Standard(identifier="MRP-227")
    assert inst.identifier == "MRP-227"


def test_edge_type_map_subjects_are_known_entity_types() -> None:
    """Every subject/object in EDGE_TYPE_MAP must be a known entity type,
    and every value list must use edge types that exist in EDGE_TYPES.
    """
    types = set(entity_schemas.ENTITY_TYPES.keys())
    edges = set(entity_schemas.EDGE_TYPES.keys())
    for (subj, obj), edge_list in entity_schemas.EDGE_TYPE_MAP.items():
        assert subj in types, f"unknown subject {subj!r}"
        assert obj in types, f"unknown object {obj!r}"
        for e in edge_list:
            assert e in edges, f"unknown edge {e!r} for ({subj}, {obj})"


def test_extract_graph_passes_entity_types_to_graphiti() -> None:
    """Pin the wiring: tasks.extract_graph must invoke
    ``graphiti.add_episode`` with ontology-resolved ``entity_types`` /
    ``edge_types`` (from the ingestion run's ontology_name/version).
    """
    src = Path(__file__).parent.parent / "app" / "tasks.py"
    text = src.read_text()
    assert text.count("entity_types=ontology_entity_types") >= 2, (
        "extract_graph must pass entity_types=ontology_entity_types to graphiti.add_episode "
        "for both the pdf-chunk and the atomic-note code paths."
    )
    assert text.count("edge_types=ontology_edge_types") >= 2
    assert "fetch_ingestion_run_ontology" in text
    assert "resolve_ontology" in text
    assert "entity_types=ENTITY_TYPES" not in text
