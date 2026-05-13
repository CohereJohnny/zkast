"""Sprint 5c — typed entity extraction via Graphiti.

Locks in the contract that ``extract_graph`` passes our Pydantic entity
schemas + edge schemas to ``graphiti.add_episode``. Without these,
Graphiti's default extractor labels every entity as the generic
``Entity``, and `entities_repo.entity_type_from_labels` collapses
everything into the residual ``"Concept"`` bucket — which is exactly
the visual bug we shipped Sprint 5c to fix.
"""

from __future__ import annotations

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


def test_every_entity_type_has_a_docstring() -> None:
    """Graphiti uses each model's docstring as the entity-type description
    presented to the LLM. An empty docstring makes the type a guess.
    """
    for name, cls in entity_schemas.ENTITY_TYPES.items():
        assert (cls.__doc__ or "").strip(), (
            f"{name} has no docstring; Graphiti can't describe it to the LLM."
        )


def test_every_entity_type_has_at_least_one_required_field() -> None:
    """BUG-010 / TD-010 — Cohere's OpenAI-compat ``response_format`` rejects
    JSON schemas whose ``object`` block has an empty ``required`` array with
    HTTP 400 "object type must have at least one required field". Every
    custom entity model passed to ``graphiti.add_episode(entity_types=...)``
    must therefore have ≥ 1 required field, or graph extraction silently
    produces 0 entities per episode.
    """
    for name, cls in entity_schemas.ENTITY_TYPES.items():
        schema = cls.model_json_schema()
        required = schema.get("required") or []
        assert required, (
            f"{name} has no required fields in its JSON schema; Cohere will "
            "reject this with 400 invalid 'json_schema' (BUG-010)."
        )


def test_every_edge_type_has_at_least_one_required_field() -> None:
    """Same constraint applies to edge type models — Graphiti calls
    Cohere with each edge type's schema to fill in typed attributes.
    """
    for name, cls in entity_schemas.EDGE_TYPES.items():
        schema = cls.model_json_schema()
        required = schema.get("required") or []
        assert required, (
            f"Edge type {name} has no required fields; Cohere will reject "
            "the schema (BUG-010)."
        )


def test_edge_types_cover_canonical_relations() -> None:
    expected_minimum = {
        "WORKS_FOR",
        "LOCATED_IN",
        "PUBLISHED",
        "CITES",
        "RELATES_TO",
    }
    assert expected_minimum.issubset(set(entity_schemas.EDGE_TYPES.keys()))


def test_edge_type_map_only_references_known_types() -> None:
    """Every (subject, object) key in EDGE_TYPE_MAP must use entity types
    that exist in ENTITY_TYPES, and every value list must use edge types
    that exist in EDGE_TYPES. Caught early before Graphiti silently drops
    the mapping at runtime.
    """
    types = set(entity_schemas.ENTITY_TYPES.keys())
    edges = set(entity_schemas.EDGE_TYPES.keys())
    for (subj, obj), candidates in entity_schemas.EDGE_TYPE_MAP.items():
        assert subj in types, f"EDGE_TYPE_MAP key references unknown type: {subj}"
        assert obj in types, f"EDGE_TYPE_MAP key references unknown type: {obj}"
        for e in candidates:
            assert e in edges, f"EDGE_TYPE_MAP value references unknown edge type: {e}"


def test_standard_identifier_is_required() -> None:
    """Standards are useless without an identifier (MRP-227, ASME XI, …).
    Standard.identifier should be a required field so the LLM can't emit
    a Standard entity without naming it.
    """
    Standard = entity_schemas.Standard
    with pytest.raises(Exception):
        Standard()  # type: ignore[call-arg]
    inst = Standard(identifier="MRP-227")
    assert inst.identifier == "MRP-227"


def test_extract_graph_passes_entity_types_to_graphiti(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the wiring: tasks.extract_graph must invoke
    ``graphiti.add_episode`` with both ``entity_types`` and ``edge_types``
    from ``app.entity_schemas``.

    We don't actually run the full task here — we just inspect the
    source of ``tasks.py`` for the literal kwargs. This is a brittle
    smoke check but it's effective: the regression we're guarding against
    is somebody removing the kwargs during a refactor.
    """
    from pathlib import Path

    src = Path(__file__).parent.parent / "app" / "tasks.py"
    text = src.read_text()
    # Two call sites: pdf-chunk episode + atomic-note episode. Both must
    # use the typed kwargs.
    assert text.count("entity_types=ENTITY_TYPES") >= 2, (
        "extract_graph must pass entity_types=ENTITY_TYPES to graphiti.add_episode "
        "for both the pdf-chunk and the atomic-note code paths."
    )
    assert text.count("edge_types=EDGE_TYPES") >= 2
    assert "from app.entity_schemas import" in text
