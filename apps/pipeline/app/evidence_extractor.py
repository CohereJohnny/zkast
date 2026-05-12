"""LangExtract-based source-grounding co-extractor.

Sprint 5c Phase 2. Graphiti gives us entities + relations but not
character-level offsets back into the source text. LangExtract is
designed exactly for that — it returns each extracted span with
a ``char_interval`` (start, end) inside the input string.

The flow inside ``tasks.py:extract_graph`` is:
1. Per episode, kick off Graphiti's ``add_episode`` and LangExtract's
   ``extract`` in parallel (under the same semaphore).
2. After both return, fuzzy-match each LangExtract span to a Graphiti
   entity by ``(normalized_name, type)``.
3. Persist matches to ``entity_evidence`` with the source character
   range and a snippet quote.

Cohere is the only LLM in this stack (Sprint 5c scope), so we route
LangExtract's OpenAI provider at the Cohere OpenAI-compatible
endpoint (``api.cohere.com/compatibility/v1``).
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# Entity classes LangExtract is asked to surface. Match the Pydantic
# taxonomy in ``entity_schemas.py`` so the fuzzy-matcher can join on
# (name, type) cleanly.
ALLOWED_CLASSES = (
    "Person",
    "Organization",
    "Location",
    "Document",
    "Standard",
    "Equipment",
    "Process",
    "Material",
    "Event",
    "Concept",
)


PROMPT_DESCRIPTION = """\
Extract every meaningful named entity from the text. For each, return:
- extraction_class: one of Person, Organization, Location, Document, Standard, Equipment, Process, Material, Event, Concept.
- extraction_text: the exact span as it appears in the input (verbatim, preserving capitalization and punctuation).
- attributes: optional small dict, e.g. {"identifier": "MRP-227"} for Standards or {"role": "Senior Engineer"} for Persons.

Rules:
- Prefer specific types (Standard, Document, Equipment, Process, Material, Person, Organization, Location, Event) over the generic Concept fallback.
- Extract each occurrence at most once per span.
- Do not invent or paraphrase — extraction_text must appear verbatim in the source.
"""


@dataclass
class EvidenceSpan:
    """One LangExtract extraction normalized to the shape our repo expects."""

    name: str
    entity_type: str
    char_start: int
    char_end: int
    quote: str
    attributes: dict[str, Any]


def _normalize_name(s: str) -> str:
    """Loose name normalization for cross-extractor matching.

    Folds case, strips punctuation, collapses whitespace, and removes
    common stop characters. The point isn't perfect — Graphiti might
    say "MRP-227" while LangExtract says "MRP 227" — but it should
    survive common variations.
    """
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[\s\-_/,.]+", " ", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return s.strip()


def _build_examples() -> list[Any]:
    """Build a small few-shot example set keyed off our entity taxonomy."""
    import langextract as lx

    return [
        lx.data.ExampleData(
            text=(
                "The Materials Reliability Program (MRP-227, Revision 2-A) was "
                "published by EPRI to guide inspection of Westinghouse "
                "Generation IV reactor internals."
            ),
            extractions=[
                lx.data.Extraction(
                    extraction_class="Standard",
                    extraction_text="MRP-227, Revision 2-A",
                    attributes={"identifier": "MRP-227", "version": "2-A"},
                ),
                lx.data.Extraction(
                    extraction_class="Organization",
                    extraction_text="EPRI",
                    attributes={"kind": "consortium"},
                ),
                lx.data.Extraction(
                    extraction_class="Equipment",
                    extraction_text="Westinghouse Generation IV reactor internals",
                    attributes={
                        "manufacturer": "Westinghouse",
                        "generation": "Generation IV",
                        "kind": "system",
                    },
                ),
            ],
        ),
        lx.data.ExampleData(
            text=(
                "Dr. Alice Example, a Senior Engineer at Acme Nuclear, presented "
                "results at the IAEA conference in Vienna."
            ),
            extractions=[
                lx.data.Extraction(
                    extraction_class="Person",
                    extraction_text="Dr. Alice Example",
                    attributes={
                        "role": "Senior Engineer",
                        "affiliation": "Acme Nuclear",
                    },
                ),
                lx.data.Extraction(
                    extraction_class="Organization",
                    extraction_text="Acme Nuclear",
                    attributes={"kind": "company"},
                ),
                lx.data.Extraction(
                    extraction_class="Organization",
                    extraction_text="IAEA",
                    attributes={"kind": "agency"},
                ),
                lx.data.Extraction(
                    extraction_class="Location",
                    extraction_text="Vienna",
                    attributes={"geo_scope": "city"},
                ),
            ],
        ),
    ]


async def extract_evidence_spans(
    *,
    text: str,
    api_key: str,
    model: str,
    base_url: str = "https://api.cohere.com/compatibility/v1",
    timeout_s: float = 60.0,
) -> list[EvidenceSpan]:
    """Run LangExtract and normalize the result to ``EvidenceSpan`` rows.

    Failures (empty response, network errors, parse errors) are caught
    and surfaced as an empty list — the caller (extract_graph) treats
    evidence as optional and never lets it block the run.
    """
    if not text or not text.strip():
        return []

    # LangExtract is sync-only; run it on a worker thread so we don't
    # block the asyncio loop while extract_graph's per-episode gather
    # is in flight.
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_run_langextract_sync, text, api_key, model, base_url),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning("evidence_extractor_timeout", timeout_s=timeout_s)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "evidence_extractor_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return []

    return _normalize_result(result, text)


def _run_langextract_sync(
    text: str, api_key: str, model: str, base_url: str
) -> Any:
    """Single synchronous LangExtract call.

    Wrapped in its own function so ``asyncio.to_thread`` can call it
    cleanly. Uses LangExtract's OpenAI provider explicitly — auto-
    detection would otherwise try to dispatch to Gemini.
    """
    import langextract as lx
    from langextract.providers import openai as lx_openai

    model_instance = lx_openai.OpenAILanguageModel(
        model_id=model,
        api_key=api_key,
        base_url=base_url,
        format_type=lx.data.FormatType.JSON,
        temperature=0.1,
        max_workers=2,
    )
    return lx.extract(
        text_or_documents=text,
        prompt_description=PROMPT_DESCRIPTION,
        examples=_build_examples(),
        model=model_instance,
        # Avoid LangExtract's automatic chunk-then-merge pass — our
        # caller already chunks at the episode boundary.
        max_char_buffer=max(len(text) + 1024, 1024),
        # ``use_schema_constraints=False`` because Cohere's OpenAI-compat
        # endpoint trips on the union schemas LangExtract emits by
        # default (we hit the same json_schema 400 storm in TD-010).
        use_schema_constraints=False,
        fence_output=True,
        show_progress=False,
    )


def _normalize_result(result: Any, original_text: str) -> list[EvidenceSpan]:
    """Convert LangExtract's AnnotatedDocument(s) into EvidenceSpan rows."""
    spans: list[EvidenceSpan] = []
    docs = result if isinstance(result, list) else [result]
    for doc in docs:
        for ext in getattr(doc, "extractions", []) or []:
            cls = getattr(ext, "extraction_class", None) or ""
            if cls not in ALLOWED_CLASSES:
                continue
            quote = getattr(ext, "extraction_text", None) or ""
            if not quote.strip():
                continue

            char_interval = getattr(ext, "char_interval", None)
            if char_interval is not None:
                start = getattr(char_interval, "start_pos", None)
                end = getattr(char_interval, "end_pos", None)
            else:
                start, end = None, None

            # LangExtract's alignment occasionally falls back to None
            # when the model paraphrased. Try to locate the verbatim
            # quote ourselves so we always have an offset to persist.
            if start is None or end is None:
                idx = original_text.find(quote)
                if idx < 0:
                    # Last-ditch: case-insensitive search
                    lower_idx = original_text.lower().find(quote.lower())
                    if lower_idx >= 0:
                        idx = lower_idx
                if idx < 0:
                    continue
                start, end = idx, idx + len(quote)

            attrs = getattr(ext, "attributes", None) or {}
            if not isinstance(attrs, dict):
                attrs = {}

            spans.append(
                EvidenceSpan(
                    name=quote.strip(),
                    entity_type=cls,
                    char_start=int(start),
                    char_end=int(end),
                    quote=quote.strip(),
                    attributes={k: str(v) for k, v in attrs.items() if v is not None},
                )
            )
    return spans


def link_spans_to_entities(
    spans: list[EvidenceSpan],
    entity_lookup: dict[tuple[str, str], str],
) -> list[tuple[str, EvidenceSpan]]:
    """Fuzzy-match LangExtract spans to Graphiti-extracted entities.

    ``entity_lookup`` is keyed by ``(normalized_name, entity_type)`` →
    ``entity_id`` (zkast canonical UUID). Returns the subset of spans
    that found a match, paired with their entity id.

    The matcher is conservative:
    1. Exact ``(normalized_name, type)`` hit
    2. ``(normalized_name, "*")`` fallback when type differs (LangExtract
       and Graphiti disagree often on Concept vs more specific type)
    3. Otherwise drop the span — better to under-link than to mislink.
    """
    linked: list[tuple[str, EvidenceSpan]] = []
    for span in spans:
        key = (_normalize_name(span.name), span.entity_type)
        eid = entity_lookup.get(key)
        if eid is None:
            # Type-agnostic fallback for the common Concept-vs-Specific
            # disagreement between the two extractors.
            for (norm_name, _t), candidate in entity_lookup.items():
                if norm_name == key[0]:
                    eid = candidate
                    break
        if eid:
            linked.append((eid, span))
    return linked


def page_for_offset(char_offset: int, page_offsets: list[int]) -> int:
    """Map a character offset within an episode body back to a page number.

    ``page_offsets`` is a list of per-page char start indices computed
    by the episode chunker. We binary-search instead of scanning so
    this stays O(log n) for long PDFs.
    """
    if not page_offsets:
        return 0
    # Simple binary search for the rightmost page_offset <= char_offset.
    lo, hi = 0, len(page_offsets) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if page_offsets[mid] <= char_offset:
            lo = mid
        else:
            hi = mid - 1
    return lo
