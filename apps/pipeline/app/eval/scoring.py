"""Sprint 6b / memory eval — scoring rubric for chat retrieval eval.

Pure-Python, no I/O. The runner persists results via these helpers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ScoreResult:
    pattern_match: bool
    pattern_hits: int
    pattern_count: int
    citation_recall: float  # fraction in [0, 1]
    citation_hits: int
    citation_count: int
    context_recall: float
    context_hits: int
    context_count: int
    refusal_correct: bool
    summary: dict[str, Any]


def _normalize(s: str) -> str:
    return (s or "").lower()


def _snapshot_retrieved_ids(retrieved_items: list[Any] | None) -> list[str]:
    ids: list[str] = []
    for item in retrieved_items or []:
        if isinstance(item, dict):
            sid = item.get("source_id") or item.get("id")
            if sid:
                ids.append(str(sid))
            continue
        sid = getattr(item, "source_id", None) or getattr(item, "id", None)
        if sid:
            ids.append(str(sid))
    return ids


def score_answer(
    *,
    answer_text: str,
    refused: bool,
    expected_answer_patterns: list[str],
    expected_entity_names: list[str],
    cited_source_kinds: list[str],
    cited_source_ids: list[str],
    cited_excerpts: list[str],
    refusal_expected: bool,
    expected_source_ids: list[str] | None = None,
    expected_context_patterns: list[str] | None = None,
    retrieved_items: list[Any] | None = None,
) -> ScoreResult:
    """Score one (question, retrieval_mode, top_k) tuple."""
    text = _normalize(answer_text)

    pattern_hits = 0
    for pat in expected_answer_patterns or []:
        try:
            if re.search(pat, text, flags=re.IGNORECASE):
                pattern_hits += 1
        except re.error:
            if pat.lower() in text:
                pattern_hits += 1
    pattern_count = len(expected_answer_patterns or [])
    pattern_match = pattern_count == 0 or pattern_hits > 0

    citation_corpus = "\n".join(
        [
            *(cited_source_ids or []),
            *(cited_excerpts or []),
        ]
    ).lower()
    citation_hits = 0
    for name in expected_entity_names or []:
        if name and name.lower() in citation_corpus:
            citation_hits += 1
    citation_count = len(expected_entity_names or [])
    citation_recall = (
        citation_hits / citation_count if citation_count > 0 else 0.0
    )

    retrieved_corpus = "\n".join(_snapshot_retrieved_ids(retrieved_items)).lower()
    for excerpt in cited_excerpts or []:
        retrieved_corpus += "\n" + (excerpt or "").lower()

    context_hits = 0
    context_targets = list(expected_source_ids or [])
    for ctx_pat in expected_context_patterns or []:
        try:
            if re.search(ctx_pat, retrieved_corpus, flags=re.IGNORECASE):
                context_hits += 1
        except re.error:
            if ctx_pat.lower() in retrieved_corpus:
                context_hits += 1
    for sid in context_targets:
        if sid and sid.lower() in retrieved_corpus:
            context_hits += 1
    context_count = len(context_targets) + len(expected_context_patterns or [])
    if context_count == 0 and context_targets:
        context_count = len(context_targets)
    context_recall = (
        context_hits / context_count if context_count > 0 else 0.0
    )

    refusal_correct = bool(refused) == bool(refusal_expected)

    summary = {
        "pattern_hits": pattern_hits,
        "pattern_count": pattern_count,
        "pattern_match": pattern_match,
        "citation_hits": citation_hits,
        "citation_count": citation_count,
        "citation_recall": citation_recall,
        "context_hits": context_hits,
        "context_count": context_count,
        "context_recall": context_recall,
        "refused": bool(refused),
        "refusal_expected": bool(refusal_expected),
        "refusal_correct": refusal_correct,
        "cited_source_kinds": list(cited_source_kinds or []),
    }

    return ScoreResult(
        pattern_match=pattern_match,
        pattern_hits=pattern_hits,
        pattern_count=pattern_count,
        citation_recall=citation_recall,
        citation_hits=citation_hits,
        citation_count=citation_count,
        context_recall=context_recall,
        context_hits=context_hits,
        context_count=context_count,
        refusal_correct=refusal_correct,
        summary=summary,
    )


def aggregate_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up per-question rows into mode/category/ability/top-k summaries."""
    if not rows:
        return {
            "modes": {},
            "categories": {},
            "abilities": {},
            "top_k": {},
        }

    def _avg(xs: list[float]) -> float:
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else 0.0

    modes: dict[str, dict[str, Any]] = {}
    categories: dict[str, dict[str, dict[str, Any]]] = {}
    abilities: dict[str, dict[str, dict[str, Any]]] = {}
    top_k: dict[int, dict[str, Any]] = {}

    def _touch_bucket(
        store: dict[str, dict[str, Any]],
        key: str,
    ) -> dict[str, Any]:
        return store.setdefault(
            key,
            {
                "n": 0,
                "pattern_match": [],
                "citation_recall": [],
                "context_recall": [],
                "refusal_correct": [],
                "latency_ms": [],
                "tokens_in": [],
                "tokens_out": [],
            },
        )

    for r in rows:
        mode = r.get("mode") or r.get("memory_system") or "unknown"
        category = r.get("category") or "unknown"
        ability = r.get("ability_type") or category
        k = int(r.get("top_k_cutoff") or 30)

        bucket = _touch_bucket(modes, mode)
        bucket["n"] += 1
        bucket["pattern_match"].append(bool(r.get("pattern_match")))
        bucket["citation_recall"].append(float(r.get("citation_recall") or 0.0))
        bucket["context_recall"].append(float(r.get("context_recall") or 0.0))
        bucket["refusal_correct"].append(bool(r.get("refusal_correct")))
        bucket["latency_ms"].append(r.get("latency_ms"))
        bucket["tokens_in"].append(r.get("tokens_in"))
        bucket["tokens_out"].append(r.get("tokens_out"))

        cat_bucket = _touch_bucket(categories.setdefault(category, {}), mode)
        cat_bucket["n"] += 1
        cat_bucket["pattern_match"].append(bool(r.get("pattern_match")))
        cat_bucket["citation_recall"].append(float(r.get("citation_recall") or 0.0))
        cat_bucket["context_recall"].append(float(r.get("context_recall") or 0.0))
        cat_bucket["refusal_correct"].append(bool(r.get("refusal_correct")))

        ab_bucket = _touch_bucket(abilities.setdefault(ability, {}), mode)
        ab_bucket["n"] += 1
        ab_bucket["pattern_match"].append(bool(r.get("pattern_match")))
        ab_bucket["citation_recall"].append(float(r.get("citation_recall") or 0.0))
        ab_bucket["context_recall"].append(float(r.get("context_recall") or 0.0))
        ab_bucket["refusal_correct"].append(bool(r.get("refusal_correct")))

        tk = _touch_bucket(top_k, str(k))
        tk["n"] += 1
        tk["pattern_match"].append(bool(r.get("pattern_match")))
        tk["citation_recall"].append(float(r.get("citation_recall") or 0.0))
        tk["context_recall"].append(float(r.get("context_recall") or 0.0))
        tk["refusal_correct"].append(bool(r.get("refusal_correct")))

    def _summarize_mode(b: dict[str, Any]) -> dict[str, Any]:
        return {
            "n": b["n"],
            "pattern_match_rate": _avg([1.0 if x else 0.0 for x in b["pattern_match"]]),
            "citation_recall_avg": _avg(b["citation_recall"]),
            "context_recall_avg": _avg(b["context_recall"]),
            "refusal_correct_rate": _avg(
                [1.0 if x else 0.0 for x in b["refusal_correct"]]
            ),
            "latency_ms_avg": _avg(
                [float(x) for x in b["latency_ms"] if isinstance(x, (int, float))]
            ),
            "tokens_in_avg": _avg(
                [float(x) for x in b["tokens_in"] if isinstance(x, (int, float))]
            ),
            "tokens_out_avg": _avg(
                [float(x) for x in b["tokens_out"] if isinstance(x, (int, float))]
            ),
        }

    def _summarize_cat(b: dict[str, Any]) -> dict[str, Any]:
        return {
            "n": b["n"],
            "pattern_match_rate": _avg([1.0 if x else 0.0 for x in b["pattern_match"]]),
            "citation_recall_avg": _avg(b["citation_recall"]),
            "context_recall_avg": _avg(b["context_recall"]),
            "refusal_correct_rate": _avg(
                [1.0 if x else 0.0 for x in b["refusal_correct"]]
            ),
        }

    return {
        "modes": {m: _summarize_mode(b) for m, b in modes.items()},
        "categories": {
            cat: {m: _summarize_cat(b) for m, b in by_mode.items()}
            for cat, by_mode in categories.items()
        },
        "abilities": {
            ab: {m: _summarize_cat(b) for m, b in by_mode.items()}
            for ab, by_mode in abilities.items()
        },
        "top_k": {int(k): _summarize_mode(b) for k, b in top_k.items()},
    }
