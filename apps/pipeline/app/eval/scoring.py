"""Sprint 6b — scoring rubric for the chat retrieval eval.

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
    refusal_correct: bool
    summary: dict[str, Any]


def _normalize(s: str) -> str:
    return (s or "").lower()


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
) -> ScoreResult:
    """Score one (question, retrieval_mode) pair.

    - ``pattern_match`` is True when at least one of
      ``expected_answer_patterns`` matches the answer text. Patterns are
      regex with ``re.IGNORECASE``.
    - ``citation_recall`` is the fraction of ``expected_entity_names``
      that appear (case-insensitive) in either ``cited_source_ids`` or
      any of the ``cited_excerpts``. A name only needs to appear once.
    - ``refusal_correct`` is True when ``refused == refusal_expected``.

    The eval intentionally measures coarse signals; the comparison UI
    surfaces the underlying retrieval records so a human can inspect
    each answer in detail.
    """
    text = _normalize(answer_text)

    pattern_hits = 0
    for pat in expected_answer_patterns or []:
        try:
            if re.search(pat, text, flags=re.IGNORECASE):
                pattern_hits += 1
        except re.error:
            # Treat a malformed pattern as a literal substring match
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

    refusal_correct = bool(refused) == bool(refusal_expected)

    summary = {
        "pattern_hits": pattern_hits,
        "pattern_count": pattern_count,
        "pattern_match": pattern_match,
        "citation_hits": citation_hits,
        "citation_count": citation_count,
        "citation_recall": citation_recall,
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
        refusal_correct=refusal_correct,
        summary=summary,
    )


def aggregate_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up per-question rows into mode-level + category-level
    summaries. Each row in ``rows`` must carry at least:
    ``{mode, category, pattern_match, citation_recall, refusal_correct,
       latency_ms, tokens_in, tokens_out}``.
    """
    if not rows:
        return {"modes": {}, "categories": {}}

    def _avg(xs: list[float]) -> float:
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else 0.0

    modes: dict[str, dict[str, Any]] = {}
    categories: dict[str, dict[str, dict[str, Any]]] = {}

    for r in rows:
        mode = r.get("mode") or "unknown"
        category = r.get("category") or "unknown"
        bucket = modes.setdefault(
            mode,
            {
                "n": 0,
                "pattern_match": [],
                "citation_recall": [],
                "refusal_correct": [],
                "latency_ms": [],
                "tokens_in": [],
                "tokens_out": [],
            },
        )
        bucket["n"] += 1
        bucket["pattern_match"].append(bool(r.get("pattern_match")))
        bucket["citation_recall"].append(float(r.get("citation_recall") or 0.0))
        bucket["refusal_correct"].append(bool(r.get("refusal_correct")))
        bucket["latency_ms"].append(r.get("latency_ms"))
        bucket["tokens_in"].append(r.get("tokens_in"))
        bucket["tokens_out"].append(r.get("tokens_out"))

        cat_bucket = categories.setdefault(category, {}).setdefault(
            mode,
            {
                "n": 0,
                "pattern_match": [],
                "citation_recall": [],
                "refusal_correct": [],
            },
        )
        cat_bucket["n"] += 1
        cat_bucket["pattern_match"].append(bool(r.get("pattern_match")))
        cat_bucket["citation_recall"].append(float(r.get("citation_recall") or 0.0))
        cat_bucket["refusal_correct"].append(bool(r.get("refusal_correct")))

    def _summarize_mode(b: dict[str, Any]) -> dict[str, Any]:
        return {
            "n": b["n"],
            "pattern_match_rate": _avg([1.0 if x else 0.0 for x in b["pattern_match"]]),
            "citation_recall_avg": _avg(b["citation_recall"]),
            "refusal_correct_rate": _avg([1.0 if x else 0.0 for x in b["refusal_correct"]]),
            "latency_ms_avg": _avg([float(x) for x in b["latency_ms"] if isinstance(x, (int, float))]),
            "tokens_in_avg": _avg([float(x) for x in b["tokens_in"] if isinstance(x, (int, float))]),
            "tokens_out_avg": _avg([float(x) for x in b["tokens_out"] if isinstance(x, (int, float))]),
        }

    def _summarize_cat(b: dict[str, Any]) -> dict[str, Any]:
        return {
            "n": b["n"],
            "pattern_match_rate": _avg([1.0 if x else 0.0 for x in b["pattern_match"]]),
            "citation_recall_avg": _avg(b["citation_recall"]),
            "refusal_correct_rate": _avg([1.0 if x else 0.0 for x in b["refusal_correct"]]),
        }

    return {
        "modes": {m: _summarize_mode(b) for m, b in modes.items()},
        "categories": {
            cat: {m: _summarize_cat(b) for m, b in by_mode.items()}
            for cat, by_mode in categories.items()
        },
    }
