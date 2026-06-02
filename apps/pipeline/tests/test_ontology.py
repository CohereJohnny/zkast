"""The generic_v1 ontology-as-data must rebuild byte-identical Graphiti schemas.

This is the behavior-neutrality guarantee for lifting entity_schemas.py into the
versioned ontology store: models built from app/ontologies/generic_v1.yaml must
produce the same model_json_schema() as the original hardcoded models, the same
edge_type_map, and the same extraction instructions.
"""

import inspect

from app import entity_schemas
from app.ontology import load_ontology_file


def _norm(model) -> dict:
    schema = model.model_json_schema()
    # Docstring indentation is behaviorally irrelevant; normalize before compare.
    desc = schema.get("description")
    if isinstance(desc, str):
        schema["description"] = inspect.cleandoc(desc)
    return schema


def test_generic_v1_entity_schemas_equivalent() -> None:
    ont = load_ontology_file("generic", "v1")
    built = ont.build_entity_types()
    assert list(built.keys()) == list(entity_schemas.ENTITY_TYPES.keys())
    for key, original in entity_schemas.ENTITY_TYPES.items():
        assert _norm(built[key]) == _norm(original), f"entity {key} schema drift"


def test_generic_v1_edge_schemas_equivalent() -> None:
    ont = load_ontology_file("generic", "v1")
    built = ont.build_edge_types()
    assert list(built.keys()) == list(entity_schemas.EDGE_TYPES.keys())
    for key, original in entity_schemas.EDGE_TYPES.items():
        assert _norm(built[key]) == _norm(original), f"edge {key} schema drift"


def test_generic_v1_edge_type_map_equivalent() -> None:
    ont = load_ontology_file("generic", "v1")
    assert ont.build_edge_type_map() == entity_schemas.EDGE_TYPE_MAP


def test_generic_v1_instructions_equivalent() -> None:
    ont = load_ontology_file("generic", "v1")
    assert ont.instructions == entity_schemas.CUSTOM_EXTRACTION_INSTRUCTIONS
