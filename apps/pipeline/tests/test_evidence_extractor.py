"""Sprint 5c Phase 2 — LangExtract evidence extraction + linking.

Locks in three contracts:
1. An empty-result LangExtract response is non-fatal (returns []).
2. Spans missing a ``char_interval`` get located by verbatim substring
   match against the original text so we always have an offset.
3. ``link_spans_to_entities`` matches on (normalized_name, type) and
   falls back to type-agnostic match for the common Concept-vs-Specific
   disagreement between Graphiti and LangExtract.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.evidence_extractor import (
    EvidenceSpan,
    _normalize_name,
    _normalize_result,
    extract_evidence_spans,
    link_spans_to_entities,
    page_for_offset,
)


def _fake_extraction(
    cls: str,
    text: str,
    start: int | None = None,
    end: int | None = None,
    attrs: dict | None = None,
):
    """Mock a langextract Extraction with the shape ``_normalize_result`` uses."""
    char_interval = None
    if start is not None and end is not None:
        char_interval = SimpleNamespace(start_pos=start, end_pos=end)
    return SimpleNamespace(
        extraction_class=cls,
        extraction_text=text,
        char_interval=char_interval,
        attributes=attrs or {},
    )


def _fake_doc(extractions):
    return SimpleNamespace(extractions=extractions)


def test_normalize_name_folds_punctuation_and_case() -> None:
    # Sprint 5c BUG-focus — Graphiti emits "MRP-227" while LangExtract
    # might emit "MRP 227" or "MRP/227". Both must normalize equal.
    assert _normalize_name("MRP-227") == _normalize_name("MRP 227")
    assert _normalize_name("MRP-227") == _normalize_name("mrp/227")
    # Case + ASCII punctuation also folds:
    assert _normalize_name("Acme, Inc.") == _normalize_name("acme inc")


def test_normalize_result_drops_classes_outside_taxonomy() -> None:
    doc = _fake_doc(
        [
            _fake_extraction("Person", "Alice", 0, 5),
            _fake_extraction("SomeOtherClass", "Bob", 10, 13),  # rejected
        ]
    )
    spans = _normalize_result(doc, "Alice ... Bob")
    assert [s.entity_type for s in spans] == ["Person"]
    assert spans[0].name == "Alice"


def test_normalize_result_locates_quotes_with_no_char_interval() -> None:
    """LangExtract's alignment occasionally returns char_interval=None.
    We must fall back to a verbatim substring search.
    """
    text = "The plant uses MRP-227 for inspection."
    doc = _fake_doc(
        [
            _fake_extraction("Standard", "MRP-227", start=None, end=None),
        ]
    )
    spans = _normalize_result(doc, text)
    assert len(spans) == 1
    assert spans[0].char_start == text.index("MRP-227")
    assert spans[0].char_end == spans[0].char_start + len("MRP-227")


def test_normalize_result_drops_unfindable_spans() -> None:
    text = "Alice founded Acme."
    doc = _fake_doc(
        [_fake_extraction("Person", "Bob", start=None, end=None)],
    )
    # Bob is not in the source; we'd rather drop than fabricate an offset.
    assert _normalize_result(doc, text) == []


def test_link_spans_exact_match() -> None:
    spans = [
        EvidenceSpan(
            name="MRP-227",
            entity_type="Standard",
            char_start=0,
            char_end=7,
            quote="MRP-227",
            attributes={},
        )
    ]
    lookup = {(_normalize_name("MRP-227"), "Standard"): "ent-uuid-1"}
    linked = link_spans_to_entities(spans, lookup)
    assert linked == [("ent-uuid-1", spans[0])]


def test_link_spans_type_agnostic_fallback() -> None:
    # Graphiti says Concept, LangExtract says Standard. The fallback path
    # should still link by normalized name.
    spans = [
        EvidenceSpan(
            name="MRP-227",
            entity_type="Standard",
            char_start=0,
            char_end=7,
            quote="MRP-227",
            attributes={},
        )
    ]
    lookup = {(_normalize_name("MRP-227"), "Concept"): "ent-uuid-1"}
    linked = link_spans_to_entities(spans, lookup)
    assert linked == [("ent-uuid-1", spans[0])]


def test_link_spans_drops_unknown() -> None:
    spans = [
        EvidenceSpan(
            name="Nope",
            entity_type="Person",
            char_start=0,
            char_end=4,
            quote="Nope",
            attributes={},
        )
    ]
    assert link_spans_to_entities(spans, {}) == []


def test_extract_evidence_spans_empty_input_returns_empty() -> None:
    out = asyncio.run(
        extract_evidence_spans(
            text="", api_key="k", model="command", base_url="https://example/"
        )
    )
    assert out == []


def test_extract_evidence_spans_error_is_non_fatal() -> None:
    """Any exception inside the sync runner is caught and surfaced as []."""
    with patch(
        "app.evidence_extractor._run_langextract_sync",
        side_effect=RuntimeError("boom"),
    ):
        out = asyncio.run(
            extract_evidence_spans(
                text="some text",
                api_key="k",
                model="command",
                base_url="https://example/",
            )
        )
    assert out == []


def test_extract_evidence_spans_timeout_returns_empty() -> None:
    """If the sync runner exceeds the timeout, we get [] rather than a
    bubbling TimeoutError that would kill the per-episode task.
    """

    def _slow_runner(*_a, **_kw):  # noqa: ARG001
        import time

        time.sleep(0.5)
        return _fake_doc([])

    with patch("app.evidence_extractor._run_langextract_sync", side_effect=_slow_runner):
        out = asyncio.run(
            extract_evidence_spans(
                text="some text",
                api_key="k",
                model="command",
                base_url="https://example/",
                timeout_s=0.05,
            )
        )
    assert out == []


def test_cohere_compat_openai_model_omits_n_param() -> None:
    """Cohere's OpenAI-compat endpoint 422s on ``n`` — our subclass must omit it."""
    from app.evidence_extractor import _cohere_compat_openai_model_class

    ModelCls = _cohere_compat_openai_model_class()
    model = ModelCls(
        model_id="command-a",
        api_key="test-key",
        base_url="https://api.cohere.com/compatibility/v1",
    )
    captured: dict = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        choice = SimpleNamespace(message=SimpleNamespace(content='{"extractions": []}'))
        return SimpleNamespace(choices=[choice])

    model._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    model._process_single_prompt("extract entities from foo", {})
    assert "n" not in captured
    assert captured.get("model") == "command-a"


def test_page_for_offset_binary_search() -> None:
    # Page offsets: [0, 100, 250, 400]
    offsets = [0, 100, 250, 400]
    assert page_for_offset(0, offsets) == 0
    assert page_for_offset(50, offsets) == 0
    assert page_for_offset(100, offsets) == 1
    assert page_for_offset(150, offsets) == 1
    assert page_for_offset(300, offsets) == 2
    assert page_for_offset(500, offsets) == 3


def test_page_for_offset_handles_empty_offsets() -> None:
    assert page_for_offset(123, []) == 0
