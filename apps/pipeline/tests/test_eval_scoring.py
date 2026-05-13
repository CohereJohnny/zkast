"""Sprint 6b — eval scoring rubric tests."""

from __future__ import annotations

from app.eval.scoring import aggregate_scores, score_answer


def test_pattern_match_any() -> None:
    r = score_answer(
        answer_text="There are 6 locations: Asia-Pacific, Australia, Canada...",
        refused=False,
        expected_answer_patterns=["\\b6\\b", "six"],
        expected_entity_names=["Asia-Pacific", "Australia", "Canada"],
        cited_source_kinds=["typed_entity"],
        cited_source_ids=["typed_entity:aggregation"],
        cited_excerpts=["Location (count=6): Asia-Pacific, Australia, Canada"],
        refusal_expected=False,
    )
    assert r.pattern_match is True
    assert r.pattern_hits >= 1
    assert r.citation_hits == 3
    assert r.citation_recall == 1.0
    assert r.refusal_correct is True


def test_partial_recall() -> None:
    r = score_answer(
        answer_text="Two of them are Canada and Japan.",
        refused=False,
        expected_answer_patterns=[],
        expected_entity_names=[
            "Asia-Pacific",
            "Australia",
            "Canada",
            "Japan",
            "Middle East",
            "North America",
        ],
        cited_source_kinds=[],
        cited_source_ids=[],
        cited_excerpts=["Canada", "Japan"],
        refusal_expected=False,
    )
    assert r.citation_hits == 2
    assert abs(r.citation_recall - (2 / 6)) < 1e-9


def test_refusal_expected_match() -> None:
    r = score_answer(
        answer_text="The workspace doesn't contain info on this.",
        refused=True,
        expected_answer_patterns=["(cannot|not|no)"],
        expected_entity_names=[],
        cited_source_kinds=[],
        cited_source_ids=[],
        cited_excerpts=[],
        refusal_expected=True,
    )
    assert r.refusal_correct is True


def test_refusal_unexpected_failure() -> None:
    r = score_answer(
        answer_text="I won't answer that.",
        refused=True,
        expected_answer_patterns=[],
        expected_entity_names=[],
        cited_source_kinds=[],
        cited_source_ids=[],
        cited_excerpts=[],
        refusal_expected=False,
    )
    assert r.refusal_correct is False


def test_aggregate_rollup() -> None:
    rows = [
        {
            "mode": "rag",
            "category": "aggregation",
            "pattern_match": False,
            "citation_recall": 0.0,
            "refusal_correct": True,
            "latency_ms": 1200,
            "tokens_in": 500,
            "tokens_out": 80,
        },
        {
            "mode": "graph",
            "category": "aggregation",
            "pattern_match": True,
            "citation_recall": 0.5,
            "refusal_correct": True,
            "latency_ms": 1500,
            "tokens_in": 800,
            "tokens_out": 90,
        },
        {
            "mode": "hybrid",
            "category": "aggregation",
            "pattern_match": True,
            "citation_recall": 1.0,
            "refusal_correct": True,
            "latency_ms": 1700,
            "tokens_in": 850,
            "tokens_out": 110,
        },
    ]
    rollup = aggregate_scores(rows)
    assert set(rollup["modes"].keys()) == {"rag", "graph", "hybrid"}
    assert rollup["modes"]["hybrid"]["citation_recall_avg"] == 1.0
    assert rollup["modes"]["rag"]["citation_recall_avg"] == 0.0
    assert "aggregation" in rollup["categories"]


def test_aggregate_empty_returns_empty_shape() -> None:
    assert aggregate_scores([]) == {"modes": {}, "categories": {}}
