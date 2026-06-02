"""Auto-tune an extraction ontology from a memory space's corpus.

Samples raw-chunk text for a workspace (optionally a single agent/memory space),
asks the LLM to propose a domain-adapted ontology starting from a base ontology,
coerces the response into our ontology shape (guaranteeing the Cohere
json_schema "at least one required field" rule), and returns a new Ontology that
the caller persists as an ``auto`` prompt-set version.

The LLM call mirrors notes_llm.py (Cohere OpenAI-compat, json_object mode).
"""

from __future__ import annotations

import json
import re
from typing import Any

import psycopg
import structlog
from openai import AsyncOpenAI

from app.graphiti_factory import COHERE_COMPAT_BASE
from app.ontology import Ontology, OntologyField, OntologyType, ontology_from_doc

logger = structlog.get_logger(__name__)


SYSTEM_PROMPT = """You are an ontology engineer for a knowledge-graph extraction pipeline.
Given sample passages from a document corpus and a BASE ontology, propose an ontology adapted to the corpus's domain.

Output STRICT JSON only with this exact shape:
{
  "entity_types": [
    {"name": "PascalCaseType", "description": "what this type is",
     "fields": [{"name": "snake_field", "description": "what it captures", "optional": true|false}]}
  ],
  "edge_types": [
    {"name": "UPPER_SNAKE_REL", "title": "PascalCaseModelName", "description": "subject -> object meaning",
     "fields": [{"name": "snake_field", "description": "...", "optional": true|false}]}
  ],
  "edge_type_map": [{"subject": "EntityTypeName", "object": "EntityTypeName", "edges": ["UPPER_SNAKE_REL"]}],
  "instructions": "plain-English guidance appended to the extractor system prompt"
}

Rules:
- 6 to 14 entity types; prefer specific domain types over a generic Concept, but keep a Concept residual bucket.
- Every entity type MUST include a required (optional=false) field named "description".
- Every edge type MUST include a required (optional=false) field named "rationale", a PascalCase "title", and an UPPER_SNAKE "name".
- Keep a generic "RELATES_TO" edge as a fallback.
- edge_type_map subjects/objects MUST be names you defined in entity_types; edges MUST be names you defined in edge_types.
- Reuse base type names where they already fit the corpus; add/rename types to fit the domain.
- Output JSON only, no prose.
"""


# Index kinds whose ``text`` is representative domain prose to sample for
# ontology auto-tuning. Atomic notes (note_zettel) carry title+body and dominate
# conversation-derived corpora; raw_chunk carries parsed document/transcript
# text. note_amem is omitted to avoid duplicating note content. Note embeddings
# have no document_id, so document-scoped sampling effectively uses raw_chunk.
SAMPLE_INDEX_KINDS: tuple[str, ...] = ("raw_chunk", "note_zettel")


def sample_corpus_texts(
    database_url: str,
    *,
    workspace_id: str,
    agent_id: str | None = None,
    document_id: str | None = None,
    kinds: tuple[str, ...] = SAMPLE_INDEX_KINDS,
    limit: int = 40,
    max_chars: int = 2000,
) -> list[str]:
    """Random sample of representative corpus text, scoped to a memory space.

    Samples ``text`` from raw chunks and atomic notes. Scope precedence (most to
    least specific): a single ``document_id`` (one source), an ``agent_id`` (an
    agent's / Slack channel's whole memory space), or the whole workspace when
    neither is given.
    """
    sql = [
        "SELECT text FROM retrieval_embeddings",
        "WHERE workspace_id = %s::uuid AND index_kind = ANY(%s)",
    ]
    args: list[Any] = [workspace_id, list(kinds)]
    if document_id:
        sql.append("AND document_id = %s::uuid")
        args.append(document_id)
    elif agent_id:
        sql.append("AND agent_id = %s::uuid")
        args.append(agent_id)
    sql.append("ORDER BY random() LIMIT %s")
    args.append(int(limit))
    with psycopg.connect(database_url) as conn:
        rows = conn.execute("\n".join(sql), tuple(args)).fetchall()
    return [str(r[0])[:max_chars] for r in rows if r and r[0]]


def _extract_json_object(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise
        return json.loads(m.group(0))


def _coerce_required_anchor(t: OntologyType, anchor: str) -> None:
    """Guarantee a type has >=1 required field (Cohere json_schema rule).

    Ensures a required field named ``anchor`` exists; if a field with that name
    exists, force it required; otherwise prepend one.
    """
    for f in t.fields:
        if f.name == anchor:
            f.optional = False
            if not (f.description or "").strip():
                f.description = "Short description grounding this in the source."
            return
    if not any(not f.optional for f in t.fields):
        t.fields.insert(
            0,
            OntologyField(
                name=anchor,
                description="Short description grounding this in the source.",
                optional=False,
            ),
        )


def _dedupe_types(types: list[OntologyType]) -> list[OntologyType]:
    seen: set[str] = set()
    out: list[OntologyType] = []
    for t in types:
        if not (t.name or "").strip() or t.name in seen:
            continue
        seen.add(t.name)
        out.append(t)
    return out


def _prune_edge_type_map(ont: Ontology) -> list[dict[str, Any]]:
    """Drop edge_type_map entries that reference undefined types/edges.

    LLMs frequently emit pairings using base/undefined type names; the map is
    only an extraction hint, so pruning dangling entries keeps the ontology
    valid without losing the well-formed pairings.
    """
    entity_names = {t.name for t in ont.entity_types}
    edge_names = {t.name for t in ont.edge_types}
    pruned: list[dict[str, Any]] = []
    for entry in ont.edge_type_map:
        subj = entry.get("subject")
        obj = entry.get("object")
        if subj not in entity_names or obj not in entity_names:
            continue
        kept = [e for e in (entry.get("edges") or []) if e in edge_names]
        if kept:
            pruned.append({"subject": subj, "object": obj, "edges": kept})
    return pruned


def coerce_proposed_ontology(doc: dict[str, Any], *, name: str, version: str) -> Ontology:
    """Build an Ontology from an LLM doc, enforcing our invariants so the result
    always passes validate_ontology: dedupe types, backfill descriptions, ensure
    a required anchor field per type, and prune dangling edge_type_map entries.
    """
    doc = dict(doc)
    doc["name"] = name
    doc["version"] = version
    ont = ontology_from_doc(doc)

    ont.entity_types = _dedupe_types(ont.entity_types)
    ont.edge_types = _dedupe_types(ont.edge_types)

    for t in ont.entity_types:
        if not (t.description or "").strip():
            t.description = f"{t.name} (auto-proposed entity type)."
        _coerce_required_anchor(t, "description")
    for t in ont.edge_types:
        if not (t.description or "").strip():
            t.description = f"{t.name} (auto-proposed relationship)."
        _coerce_required_anchor(t, "rationale")

    ont.edge_type_map = _prune_edge_type_map(ont)
    return ont


def build_user_content(samples: list[str], base: Ontology) -> str:
    base_entities = ", ".join(t.name for t in base.entity_types)
    base_edges = ", ".join(t.name for t in base.edge_types)
    joined = "\n\n---\n\n".join(f"[{i}] {s}" for i, s in enumerate(samples))
    return (
        f"BASE entity types: {base_entities}\n"
        f"BASE edge types: {base_edges}\n\n"
        f"SAMPLE PASSAGES ({len(samples)}):\n\n{joined}\n\n"
        "Propose the domain-adapted ontology as JSON only."
    )


async def autotune_ontology(
    *,
    api_key: str,
    model: str,
    samples: list[str],
    base: Ontology,
    name: str,
    version: str,
    timeout_s: float = 90.0,
) -> Ontology:
    """Single structured LLM call -> coerced Ontology (not yet validated/persisted)."""
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=COHERE_COMPAT_BASE,
        timeout=timeout_s,
        max_retries=1,
    )
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_content(samples, base)},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or ""
    if not raw.strip():
        raise RuntimeError("Auto-tune LLM returned an empty response")
    data = _extract_json_object(raw)
    return coerce_proposed_ontology(data, name=name, version=version)
