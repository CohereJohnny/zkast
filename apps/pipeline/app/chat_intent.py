"""Sprint 6b / TD-015 — chat intent router.

Classifies a user query into one of four intent classes so the
``hybrid`` retrieval strategy can dispatch to the appropriate
deterministic handler:

- ``aggregation`` — "how many", "list all", "count", "what types"
- ``multi_hop`` — "how is A related to B", "path from A to B",
  "what connects A and B"
- ``refusal_or_unknown`` — sentinel for queries we will not try to
  answer with a deterministic handler (e.g. "what's the population of
  France?" against an oil & gas corpus). Hybrid then falls back to the
  graph-strategy retrieval pipeline.
- ``vector`` — default, semantic question that the regular ranker
  handles best.

The router is intentionally deterministic and rule-based for this
sprint. An LLM-backed classifier is reserved for Sprint 7+ once we
have eval data to know when the heuristics are wrong.

The output also surfaces structured "slots" so the typed-entity and
path handlers don't have to re-parse the query:

- ``entity_types[]`` — workspace entity types named in the query
  (matched case-insensitively against ``entities.type``).
- ``mentioned_entities[]`` — canonical entity names mentioned in the
  query (case-insensitive substring match against
  ``entities.canonical_name``). The path handler uses these to pick
  endpoints for a traversal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row


IntentKind = str  # one of: "vector" | "aggregation" | "multi_hop" | "refusal_or_unknown"


_AGGREGATION_PATTERNS = [
    re.compile(r"\bhow\s+many\b", re.I),
    re.compile(r"\bhow\s+much\b", re.I),
    re.compile(r"\blist\s+(?:all|the|every)\b", re.I),
    re.compile(r"\b(name|enumerate|show)\s+(?:all|the|every)\b", re.I),
    re.compile(r"\bcount\s+(?:of|by|the)?\b", re.I),
    re.compile(r"\bwhat\s+(?:are\s+the\s+)?(?:types|kinds)\b", re.I),
    re.compile(r"\bnumber\s+of\b", re.I),
    re.compile(r"\bwhich\s+(?:are\s+all|are\s+the)\b", re.I),
]

_MULTI_HOP_PATTERNS = [
    re.compile(r"\bhow\s+(?:is|are)\s+.+\s+(?:related|connected)\s+to\b", re.I),
    re.compile(r"\bpath\s+from\b.+\bto\b", re.I),
    re.compile(r"\bwhat\s+connects\b", re.I),
    re.compile(r"\bwhat\s+(?:is|are)\s+the\s+(?:relationship|connection)s?\s+between\b", re.I),
    re.compile(r"\brelationship\s+between\b", re.I),
    re.compile(r"\blink\s+between\b", re.I),
]


@dataclass
class IntentSlots:
    """Structured slots extracted alongside the intent classification."""

    entity_types: list[str] = field(default_factory=list)
    mentioned_entities: list[str] = field(default_factory=list)


@dataclass
class IntentClassification:
    kind: IntentKind
    slots: IntentSlots
    matched_patterns: list[str] = field(default_factory=list)

    def is_aggregation(self) -> bool:
        return self.kind == "aggregation"

    def is_multi_hop(self) -> bool:
        return self.kind == "multi_hop"


def _list_entity_types(database_url: str, workspace_id: str) -> list[str]:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            "SELECT DISTINCT type FROM entities WHERE workspace_id = %s::uuid",
            (workspace_id,),
        ).fetchall()
    return [str(r["type"]) for r in rows if r.get("type")]


def _list_entity_names(database_url: str, workspace_id: str) -> list[dict[str, Any]]:
    """Return ``[{id, canonical_name, type}]`` for every workspace entity.

    Used by ``classify`` to extract mentioned-entity slots. For
    workspaces in the low thousands of entities this is fine; if we ever
    push past ~10k entities per workspace we should switch to a typeahead
    lookup against the existing ``search_entities_typeahead`` helper.
    """
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            """
            SELECT id::text AS id, canonical_name, type
            FROM entities
            WHERE workspace_id = %s::uuid
              AND canonical_name IS NOT NULL
              AND length(canonical_name) >= 3
            """,
            (workspace_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _extract_entity_type_slots(query_text: str, workspace_types: list[str]) -> list[str]:
    """Match singular and plural forms of workspace entity types against
    the query. Returns the matched canonical type names ordered by
    the workspace ordering (so the handler's downstream output is
    deterministic).
    """
    if not query_text or not workspace_types:
        return []
    q = query_text.lower()
    matched: list[str] = []
    for t in workspace_types:
        tl = t.lower()
        # Try the literal type, its plural ("s"), and a permissive
        # word-boundary match so "Locations" matches "Location".
        candidates = {tl, f"{tl}s", f"{tl}es"}
        if any(re.search(rf"\b{re.escape(c)}\b", q) for c in candidates):
            matched.append(t)
    return matched


def _extract_entity_name_slots(
    query_text: str,
    entities: list[dict[str, Any]],
    *,
    max_matches: int = 4,
) -> list[str]:
    """Pull canonical entity names mentioned in the query.

    Case-insensitive substring match, longest names first so that
    "Probabilistic Safety Assessment" wins over "Safety". Returns up
    to ``max_matches`` names so the path handler doesn't have to
    enumerate every possible pair.
    """
    if not query_text or not entities:
        return []
    q = query_text.lower()
    ranked = sorted(
        entities, key=lambda e: len(str(e.get("canonical_name") or "")), reverse=True
    )
    out: list[str] = []
    used_spans: list[tuple[int, int]] = []
    for ent in ranked:
        if len(out) >= max_matches:
            break
        name = str(ent.get("canonical_name") or "").strip()
        if len(name) < 3:
            continue
        idx = q.find(name.lower())
        if idx < 0:
            continue
        end = idx + len(name)
        if any(not (end <= s or idx >= e) for s, e in used_spans):
            continue
        out.append(name)
        used_spans.append((idx, end))
    return out


def _matches_any(query_text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    return [p.pattern for p in patterns if p.search(query_text)]


def classify(
    database_url: str,
    *,
    workspace_id: str,
    query_text: str,
) -> IntentClassification:
    """Classify a chat query into an intent class + extract slots.

    Heuristic priority: aggregation > multi-hop > vector. We bias
    toward aggregation because (a) it's the failure mode BUG-013
    documented and (b) aggregation handlers are cheap and fall back
    cleanly to vector retrieval when slot extraction fails.
    """
    if not query_text or not query_text.strip():
        return IntentClassification(
            kind="refusal_or_unknown",
            slots=IntentSlots(),
        )

    workspace_types = _list_entity_types(database_url, workspace_id)
    entities = _list_entity_names(database_url, workspace_id)

    entity_types = _extract_entity_type_slots(query_text, workspace_types)
    mentioned = _extract_entity_name_slots(query_text, entities)
    slots = IntentSlots(entity_types=entity_types, mentioned_entities=mentioned)

    agg_matches = _matches_any(query_text, _AGGREGATION_PATTERNS)
    if agg_matches:
        return IntentClassification(
            kind="aggregation", slots=slots, matched_patterns=agg_matches
        )

    multi_matches = _matches_any(query_text, _MULTI_HOP_PATTERNS)
    # Multi-hop needs two entity mentions to be actionable. With fewer
    # we fall back to vector retrieval rather than hallucinate a path.
    if multi_matches and len(mentioned) >= 2:
        return IntentClassification(
            kind="multi_hop", slots=slots, matched_patterns=multi_matches
        )

    return IntentClassification(kind="vector", slots=slots)
