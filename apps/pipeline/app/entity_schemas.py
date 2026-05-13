"""Custom Pydantic schemas passed to ``graphiti.add_episode(entity_types=...)``.

Without these, Graphiti's default extractor labels every entity as the
generic ``Entity`` and our canonical mirror collapses everything to a
single ``"Concept"`` type. The result is a sea of same-colored nodes in
the graph viz (Sprint 5c BUG-focus).

Each model is intentionally lean — Graphiti's per-episode LLM call fills
in the listed fields, and any field marked with a non-trivial
description significantly improves recall on Cohere Command. We keep
the field set to the highest-value attributes per type and let
free-text spill into ``description``.

Edge types mirror the canonical relation vocabulary from
[specs/datamodel.md](../../specs/datamodel.md). Where the natural
relation isn't well-described by a typed model we fall back to
``RelatesTo``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Entity types
# ---------------------------------------------------------------------------


# IMPORTANT — Cohere's OpenAI-compat endpoint rejects ``response_format``
# JSON schemas whose ``object`` blocks have no required fields with
# ``400 invalid 'json_schema' provided: object type must have at least one
# required field`` (BUG-010, ref TD-010). Every model below must therefore
# carry at least one required field. We use a required ``description: str``
# as the universal anchor — the LLM can always produce a short summary
# from context, and the field is distinct from Graphiti's own
# ``EntityNode.name`` so there's no collision.


class Person(BaseModel):
    """A human individual (researcher, executive, author, regulator, etc.)."""

    description: str = Field(
        description="One short sentence describing this person in context (role, affiliation, why they matter)."
    )
    role: str | None = Field(
        default=None,
        description="The person's role or title at the time of the document, e.g. 'Senior Engineer', 'Plant Manager'.",
    )
    affiliation: str | None = Field(
        default=None,
        description="Organization, agency, or institution the person is associated with.",
    )


class Organization(BaseModel):
    """A company, agency, consortium, university, or other formal entity."""

    description: str = Field(
        description="One short sentence describing what this organization does and its relevance to the document."
    )
    kind: str | None = Field(
        default=None,
        description="One of: company, agency, consortium, university, vendor, regulator, other.",
    )
    country: str | None = Field(
        default=None,
        description="Primary country or jurisdiction, if known.",
    )


class Location(BaseModel):
    """A place, facility, region, or country."""

    description: str = Field(
        description="One short sentence describing this location and its role in the document."
    )
    geo_scope: str | None = Field(
        default=None,
        description="One of: facility, plant, region, country, sub-region.",
    )


class Document(BaseModel):
    """A formal document referenced by the source PDF — report, standard, regulation, paper."""

    description: str = Field(
        description="One short sentence describing this document and how it relates to the source."
    )
    doc_type: str | None = Field(
        default=None,
        description="One of: standard, report, regulation, paper, guideline, manual, other.",
    )
    identifier: str | None = Field(
        default=None,
        description="Canonical identifier if any (e.g. 'MRP-227', 'NUREG-1801', 'EPRI 1012081').",
    )
    issuing_org: str | None = Field(
        default=None,
        description="Publishing or issuing organization.",
    )


class Standard(BaseModel):
    """A formal technical standard or specification (ASME, ISO, IEEE, ASTM, …)."""

    identifier: str = Field(
        description="The standard's canonical identifier (e.g. 'ASME Section XI', 'ISO 17636-1').",
    )
    description: str | None = Field(
        default=None,
        description="One short sentence describing what the standard covers.",
    )
    issuing_body: str | None = Field(
        default=None,
        description="The standards-development organization.",
    )
    version: str | None = Field(
        default=None,
        description="Edition / revision / year if specified.",
    )


class Equipment(BaseModel):
    """A piece of hardware, plant, component, or technology referenced as a thing in the world."""

    description: str = Field(
        description="One short sentence describing this piece of equipment and its role."
    )
    kind: str | None = Field(
        default=None,
        description="One of: component, system, plant, instrument, fixture, other.",
    )
    manufacturer: str | None = Field(
        default=None,
        description="Manufacturer or vendor, if named.",
    )
    generation: str | None = Field(
        default=None,
        description="Generation, model, or design class (e.g. 'Generation III+', 'Westinghouse 4-loop').",
    )


class Process(BaseModel):
    """A named procedure, methodology, technique, or workflow."""

    description: str = Field(
        description="One short sentence describing what the process does and where it applies."
    )
    domain: str | None = Field(
        default=None,
        description="The technical domain of the process (e.g. 'NDE', 'aging management', 'risk assessment').",
    )


class Material(BaseModel):
    """A substance, alloy, metal, composite, or chemical compound."""

    description: str = Field(
        description="One short sentence describing this material and its usage in context."
    )
    composition: str | None = Field(
        default=None,
        description="Brief composition descriptor (e.g. 'austenitic stainless steel', 'Inconel 600').",
    )


class Event(BaseModel):
    """A specific occurrence or milestone with a clear time anchor (incident, release, ruling, etc.)."""

    description: str = Field(
        description="One short sentence describing the event and its significance."
    )
    when: str | None = Field(
        default=None,
        description="Free-text time anchor as it appears in the source, if any.",
    )


class Concept(BaseModel):
    """A general technical concept, phenomenon, mechanism, or topic.

    Use this only when none of the more specific types fit. The graph
    legend treats this as the residual bucket.
    """

    description: str = Field(
        description="One short sentence describing the concept and how it relates to the document."
    )
    domain: str | None = Field(
        default=None,
        description="Optional technical domain (e.g. 'materials science', 'reactor physics').",
    )


# Public dict — exactly the shape Graphiti expects for ``entity_types=``.
ENTITY_TYPES: dict[str, type[BaseModel]] = {
    "Person": Person,
    "Organization": Organization,
    "Location": Location,
    "Document": Document,
    "Standard": Standard,
    "Equipment": Equipment,
    "Process": Process,
    "Material": Material,
    "Event": Event,
    "Concept": Concept,
}


# ---------------------------------------------------------------------------
# Edge types
# ---------------------------------------------------------------------------


# Same Cohere ``json_schema`` constraint applies to edge type models: each
# must declare at least one required field. We use ``rationale: str`` so the
# LLM can ground every typed edge with a short justification — useful for
# the relationships' ``fact`` column and for downstream review.


class WorksFor(BaseModel):
    """A person works for / is employed by / is affiliated with an organization."""

    rationale: str = Field(
        description="One short clause justifying this relationship from the text."
    )
    role: str | None = Field(default=None)


class LocatedIn(BaseModel):
    """The subject is physically located within the target location/region."""

    rationale: str = Field(
        description="One short clause justifying this relationship from the text."
    )


class Published(BaseModel):
    """The subject (org or person) published or authored the target document/standard."""

    rationale: str = Field(
        description="One short clause justifying this relationship from the text."
    )
    when: str | None = Field(default=None)


class Cites(BaseModel):
    """The subject cites, references, or relies on the target document/standard."""

    rationale: str = Field(
        description="One short clause justifying this relationship from the text."
    )


class Manages(BaseModel):
    """The subject manages, owns, or is responsible for the target entity."""

    rationale: str = Field(
        description="One short clause justifying this relationship from the text."
    )


class Inspects(BaseModel):
    """The subject inspects, monitors, or evaluates the target entity."""

    rationale: str = Field(
        description="One short clause justifying this relationship from the text."
    )


class Mitigates(BaseModel):
    """The subject mitigates, addresses, or counters the target process/concept/event."""

    rationale: str = Field(
        description="One short clause justifying this relationship from the text."
    )


class RelatesTo(BaseModel):
    """Generic semantic relation when no more specific edge type fits."""

    rationale: str = Field(
        description="One short clause justifying this relationship from the text."
    )


EDGE_TYPES: dict[str, type[BaseModel]] = {
    "WORKS_FOR": WorksFor,
    "LOCATED_IN": LocatedIn,
    "PUBLISHED": Published,
    "CITES": Cites,
    "MANAGES": Manages,
    "INSPECTS": Inspects,
    "MITIGATES": Mitigates,
    "RELATES_TO": RelatesTo,
}


# Optional ``edge_type_map`` hint for Graphiti — it restricts which edge
# types are even *considered* between a given (subject_type, object_type)
# pair. Pruning the candidate set sharply improves the LLM's edge-type
# precision on Cohere Command.
#
# Wildcards (``"Entity"``) match any type Graphiti decides not to classify
# under one of our typed models.
EDGE_TYPE_MAP: dict[tuple[str, str], list[str]] = {
    ("Person", "Organization"): ["WORKS_FOR", "RELATES_TO"],
    ("Organization", "Document"): ["PUBLISHED", "CITES", "RELATES_TO"],
    ("Organization", "Standard"): ["PUBLISHED", "CITES", "RELATES_TO"],
    ("Organization", "Location"): ["LOCATED_IN", "RELATES_TO"],
    ("Document", "Document"): ["CITES", "RELATES_TO"],
    ("Document", "Standard"): ["CITES", "RELATES_TO"],
    ("Standard", "Standard"): ["CITES", "RELATES_TO"],
    ("Process", "Concept"): ["MITIGATES", "RELATES_TO"],
    ("Process", "Equipment"): ["INSPECTS", "MITIGATES", "RELATES_TO"],
    ("Process", "Material"): ["INSPECTS", "MITIGATES", "RELATES_TO"],
    ("Person", "Equipment"): ["MANAGES", "INSPECTS", "RELATES_TO"],
    ("Organization", "Equipment"): ["MANAGES", "RELATES_TO"],
}


# Plain-English extraction guidance appended to Graphiti's system prompt.
# Tested to improve type recall vs the default prompt on Cohere Command on
# technical-domain PDFs (nuclear, aerospace, biomedical).
CUSTOM_EXTRACTION_INSTRUCTIONS = """\
Prefer specific entity types over the generic Concept fallback. In particular:
- Use Standard when an entity has an identifier like 'MRP-227', 'ISO 17636', 'ASME Section XI'.
- Use Document for named reports, guidelines, or technical publications even without a standard identifier.
- Use Equipment for components, systems, or instruments referenced as physical things.
- Use Process for named procedures, methodologies, or workflows.
- Use Material for alloys, metals, composites, or chemical substances.
- Only use Concept when none of the more specific types fit.

For relationships, prefer specific edge types from the provided list. Only fall back to RELATES_TO when none of the more specific types describe the relation.
"""
