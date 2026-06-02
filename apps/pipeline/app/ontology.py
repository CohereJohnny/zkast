"""Versioned ontology / prompt-set representation.

The extraction ontology (entity types, edge types, edge-type map, and extraction
instructions) was hardcoded as Pydantic models in ``entity_schemas.py``. This
module represents the same ontology as DATA so it can be versioned, edited, and
auto-tuned, and rebuilds the equivalent Pydantic models that Graphiti's
``add_episode(entity_types=..., edge_types=...)`` expects.

Faithfulness requirement: models rebuilt from the ``generic_v1`` ontology data
must produce byte-identical ``model_json_schema()`` to the original hardcoded
models, so swapping the source is behavior-neutral (see tests/test_ontology.py).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, create_model

ONTOLOGIES_DIR = Path(__file__).resolve().parent / "ontologies"


@dataclass
class OntologyField:
    name: str
    description: str | None = None
    optional: bool = False  # str | None with a default when True; required str otherwise
    default: Any = None


@dataclass
class OntologyType:
    name: str  # registry key (e.g. entity "Person", edge "WORKS_FOR")
    description: str  # becomes the Pydantic model docstring (type description in the prompt)
    fields: list[OntologyField] = field(default_factory=list)
    # Pydantic model class name / json-schema title. Defaults to ``name``; edge
    # types differ (key "WORKS_FOR" -> class title "WorksFor").
    title: str | None = None


@dataclass
class Ontology:
    name: str
    version: str
    entity_types: list[OntologyType] = field(default_factory=list)
    edge_types: list[OntologyType] = field(default_factory=list)
    # Each entry: {"subject": str, "object": str, "edges": [str, ...]}
    edge_type_map: list[dict[str, Any]] = field(default_factory=list)
    instructions: str = ""

    # --- builders: data -> the structures Graphiti expects -----------------
    def build_entity_types(self) -> dict[str, type[BaseModel]]:
        return {t.name: _build_model(t) for t in self.entity_types}

    def build_edge_types(self) -> dict[str, type[BaseModel]]:
        return {t.name: _build_model(t) for t in self.edge_types}

    def build_edge_type_map(self) -> dict[tuple[str, str], list[str]]:
        return {
            (entry["subject"], entry["object"]): list(entry["edges"])
            for entry in self.edge_type_map
        }

    def to_doc(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "entity_types": [_type_to_doc(t) for t in self.entity_types],
            "edge_types": [_type_to_doc(t) for t in self.edge_types],
            "edge_type_map": self.edge_type_map,
            "instructions": self.instructions,
        }


def _build_model(t: OntologyType) -> type[BaseModel]:
    field_defs: dict[str, Any] = {}
    for f in t.fields:
        if f.optional:
            if f.description is None:
                field_defs[f.name] = (str | None, Field(default=f.default))
            else:
                field_defs[f.name] = (str | None, Field(default=f.default, description=f.description))
        else:
            if f.description is None:
                field_defs[f.name] = (str, ...)
            else:
                field_defs[f.name] = (str, Field(description=f.description))
    doc = inspect.cleandoc(t.description) if t.description else None
    model = create_model(t.title or t.name, __doc__=doc, **field_defs)
    return model


def _type_to_doc(t: OntologyType) -> dict[str, Any]:
    return {
        "name": t.name,
        "title": t.title,
        "description": t.description,
        "fields": [
            {
                "name": f.name,
                "description": f.description,
                "optional": f.optional,
                "default": f.default,
            }
            for f in t.fields
        ],
    }


def ontology_from_doc(doc: dict[str, Any]) -> Ontology:
    def _types(items: list[dict[str, Any]]) -> list[OntologyType]:
        out: list[OntologyType] = []
        for it in items or []:
            fields = [
                OntologyField(
                    name=f["name"],
                    description=f.get("description"),
                    optional=bool(f.get("optional", False)),
                    default=f.get("default"),
                )
                for f in it.get("fields", [])
            ]
            out.append(
                OntologyType(
                    name=it["name"],
                    description=it["description"],
                    fields=fields,
                    title=it.get("title"),
                )
            )
        return out

    return Ontology(
        name=str(doc["name"]),
        version=str(doc["version"]),
        entity_types=_types(doc.get("entity_types", [])),
        edge_types=_types(doc.get("edge_types", [])),
        edge_type_map=list(doc.get("edge_type_map", [])),
        instructions=str(doc.get("instructions", "")),
    )


def validate_ontology(ont: Ontology) -> list[str]:
    """Return a list of human-readable validation errors (empty = valid).

    Enforces the business rules from the harness OpenSpec plus the Cohere
    json_schema constraint that every type must carry at least one REQUIRED
    field (BUG-010), so the rebuilt models never produce an invalid schema.
    """
    errors: list[str] = []
    if not ont.entity_types:
        errors.append("at least one entity type is required")

    entity_names = {t.name for t in ont.entity_types}
    edge_names = {t.name for t in ont.edge_types}

    for kind, types in (("entity", ont.entity_types), ("edge", ont.edge_types)):
        seen: set[str] = set()
        for t in types:
            if not (t.name or "").strip():
                errors.append(f"{kind} type is missing a name")
                continue
            if t.name in seen:
                errors.append(f"duplicate {kind} type name {t.name!r}")
            seen.add(t.name)
            if not (t.description or "").strip():
                errors.append(f"{kind} type {t.name!r} is missing a description")
            if not any(not f.optional for f in t.fields):
                errors.append(
                    f"{kind} type {t.name!r} must have at least one required (non-optional) field"
                )
            for f in t.fields:
                if not (f.name or "").strip():
                    errors.append(f"{kind} type {t.name!r} has a field without a name")

    for i, entry in enumerate(ont.edge_type_map):
        subj = entry.get("subject")
        obj = entry.get("object")
        if subj not in entity_names:
            errors.append(f"edge_type_map[{i}] subject {subj!r} is not a defined entity type")
        if obj not in entity_names:
            errors.append(f"edge_type_map[{i}] object {obj!r} is not a defined entity type")
        for e in entry.get("edges") or []:
            if e not in edge_names:
                errors.append(f"edge_type_map[{i}] references undefined edge type {e!r}")

    return errors


def load_ontology_file(name: str, version: str) -> Ontology:
    """Load a config-as-code ontology from ``app/ontologies/<name>_<version>.yaml``."""
    path = ONTOLOGIES_DIR / f"{name}_{version}.yaml"
    doc = yaml.safe_load(path.read_text())
    return ontology_from_doc(doc)
