"""Auto-tune ontology coercion: LLM proposals must be coerced into a valid,
persistable ontology (every type gets a required anchor field, etc.)."""

from app.ontology import load_ontology_file, validate_ontology
from app.ontology_autotune import build_user_content, coerce_proposed_ontology


def test_coerce_injects_required_anchor_when_all_optional() -> None:
    # LLM proposed a type whose only field is optional, and an edge with no
    # required field — coercion must make them valid.
    doc = {
        "entity_types": [
            {"name": "Reactor", "description": "A reactor.",
             "fields": [{"name": "vendor", "description": "maker", "optional": True}]},
        ],
        "edge_types": [
            {"name": "COOLS", "title": "Cools", "description": "x cools y", "fields": []},
        ],
        "edge_type_map": [{"subject": "Reactor", "object": "Reactor", "edges": ["COOLS"]}],
        "instructions": "Prefer specific types.",
    }
    ont = coerce_proposed_ontology(doc, name="nuclear", version="v1")
    assert ont.name == "nuclear" and ont.version == "v1"
    # Coercion guarantees validity (description anchor on entity, rationale on edge).
    assert validate_ontology(ont) == []
    reactor = next(t for t in ont.entity_types if t.name == "Reactor")
    assert any(f.name == "description" and not f.optional for f in reactor.fields)
    cools = next(t for t in ont.edge_types if t.name == "COOLS")
    assert any(f.name == "rationale" and not f.optional for f in cools.fields)


def test_coerce_forces_existing_anchor_required() -> None:
    doc = {
        "entity_types": [
            {"name": "Thing", "description": "A thing.",
             "fields": [{"name": "description", "description": "d", "optional": True}]},
        ],
        "edge_types": [],
        "edge_type_map": [],
        "instructions": "",
    }
    ont = coerce_proposed_ontology(doc, name="x", version="v1")
    desc = next(f for f in ont.entity_types[0].fields if f.name == "description")
    assert desc.optional is False


def test_coerce_prunes_dangling_edge_type_map() -> None:
    # Reproduces the observed failure: the LLM proposed domain entity types but
    # an edge_type_map referencing base/undefined types (Person, Location, ...).
    doc = {
        "entity_types": [
            {"name": "SolutionComponent", "description": "A component.",
             "fields": [{"name": "description", "description": "d", "optional": False}]},
            {"name": "Integration", "description": "An integration.",
             "fields": [{"name": "description", "description": "d", "optional": False}]},
        ],
        "edge_types": [
            {"name": "INTEGRATES_WITH", "title": "IntegratesWith", "description": "x integrates y",
             "fields": [{"name": "rationale", "description": "why", "optional": False}]},
            {"name": "RELATES_TO", "title": "RelatesTo", "description": "generic",
             "fields": [{"name": "rationale", "description": "why", "optional": False}]},
        ],
        "edge_type_map": [
            {"subject": "Person", "object": "Location", "edges": ["RELATES_TO"]},  # undefined types
            {"subject": "SolutionComponent", "object": "Integration",
             "edges": ["INTEGRATES_WITH", "NOPE"]},  # valid pair, one bad edge
        ],
        "instructions": "Prefer specific types.",
    }
    ont = coerce_proposed_ontology(doc, name="solution-architecture", version="v1")
    # The whole ontology must be persistable.
    assert validate_ontology(ont) == []
    # Dangling entry dropped; valid entry kept with the bad edge filtered out.
    assert ont.edge_type_map == [
        {"subject": "SolutionComponent", "object": "Integration", "edges": ["INTEGRATES_WITH"]}
    ]


def test_build_user_content_includes_base_and_samples() -> None:
    base = load_ontology_file("generic", "v1")
    content = build_user_content(["alpha passage", "beta passage"], base)
    assert "BASE entity types:" in content
    assert "Person" in content  # a base entity type name
    assert "alpha passage" in content and "beta passage" in content
    assert "SAMPLE PASSAGES (2)" in content
