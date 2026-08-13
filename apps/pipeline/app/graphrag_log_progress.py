"""Parse GraphRAG indexing-engine.log lines into theater progress events."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

StageId = Literal["graphrag_indexing", "building_graph", "extracting_graph"]

_WORKFLOW_STARTED = re.compile(r"Workflow started:\s+(\w+)")
_WORKFLOW_COMPLETED = re.compile(r"Workflow (\w+) completed successfully")
_EXTRACT_PROGRESS = re.compile(r"extract graph progress:\s*(\d+)\s*/\s*(\d+)", re.I)
_CHUNK_PROGRESS = re.compile(r"chunker progress:\s*(\d+)\s*/\s*(\d+)", re.I)
_SUMMARIZE_PROGRESS = re.compile(
    r"Summarize entity/relationship description progress:\s*(\d+)\s*/\s*(\d+)", re.I
)
_EMBED_PROGRESS = re.compile(r"generate embeddings progress:\s*(\d+)\s*/\s*(\d+)", re.I)
_COMMUNITY_PROGRESS = re.compile(
    r"level \d+ summarize communities progress:\s*(\d+)\s*/\s*(\d+)", re.I
)

WORKFLOW_NARRATIVE_START: dict[str, str] = {
    "load_input_documents": "Gathering corpus documents from memory into the GraphRAG workspace…",
    "create_base_text_units": "Breaking documents into passages the model can digest — chunk by chunk…",
    "create_final_documents": "Normalizing document records before extraction begins…",
    "extract_graph": (
        "Starting entity extraction — reading each passage for people, orgs, concepts, and how they connect…"
    ),
    "finalize_graph": "Merging duplicate entities and tightening the graph structure…",
    "extract_covariates": "Pulling structured claims and attributes onto the graph…",
    "create_communities": "Clustering related entities into thematic communities…",
    "create_final_text_units": "Linking text units to communities for downstream reporting…",
    "create_community_reports": (
        "Writing community reports — zooming out to summarize each cluster (this part takes a while)…"
    ),
    "generate_text_embeddings": "Embedding entity descriptions so global search can retrieve them…",
}

WORKFLOW_NARRATIVE_DONE: dict[str, str] = {
    "load_input_documents": "Corpus loaded — documents staged for indexing",
    "create_base_text_units": "Chunking complete — text units ready for extraction",
    "create_final_documents": "Document records finalized",
    "extract_graph": "Entity extraction finished — graph populated from the full corpus",
    "finalize_graph": "Graph finalized and deduplicated",
    "extract_covariates": "Covariates attached to the graph",
    "create_communities": "Communities detected — thematic clusters identified",
    "create_final_text_units": "Text units aligned with communities",
    "create_community_reports": "Community reports drafted — global-search summaries ready",
    "generate_text_embeddings": "Embeddings stored — index ready for retrieval",
}

WORKFLOW_STAGE: dict[str, StageId] = {
    "load_input_documents": "graphrag_indexing",
    "create_base_text_units": "graphrag_indexing",
    "create_final_documents": "graphrag_indexing",
    "extract_graph": "building_graph",
    "finalize_graph": "building_graph",
    "extract_covariates": "building_graph",
    "summarize_descriptions": "building_graph",
    "create_communities": "extracting_graph",
    "create_final_text_units": "extracting_graph",
    "summarize_communities": "extracting_graph",
    "create_community_reports": "extracting_graph",
    "generate_text_embeddings": "extracting_graph",
}

# Inclusive percent ranges per workflow (approximate GraphRAG runtime profile).
WORKFLOW_PCT: dict[str, tuple[int, int]] = {
    "load_input_documents": (12, 14),
    "create_base_text_units": (14, 18),
    "create_final_documents": (18, 19),
    "extract_graph": (19, 72),
    "summarize_descriptions": (72, 76),
    "finalize_graph": (76, 78),
    "extract_covariates": (78, 80),
    "create_communities": (80, 84),
    "summarize_communities": (84, 88),
    "create_final_text_units": (88, 89),
    "create_community_reports": (89, 96),
    "generate_text_embeddings": (96, 99),
}

_PROGRESS_KIND_WORKFLOW: dict[str, str] = {
    "chunk": "create_base_text_units",
    "extract": "extract_graph",
    "summarize_descriptions": "summarize_descriptions",
    "summarize_communities": "summarize_communities",
    "embeddings": "generate_text_embeddings",
}

_EXTRACT_THOUGHTS: dict[int, str] = {
    1: "Opening the corpus — scanning the first documents for named entities and relationships…",
    25: "Quarter through — patterns in names, orgs, and topics are emerging from the archive",
    50: "Halfway — wiring extracted entities into a growing knowledge graph",
    75: "Past three-quarters — the graph skeleton is dense; finishing the long tail of documents",
    90: "Final stretch — last documents getting the extraction pass",
    100: "Full corpus scanned — every document yielded entities and edges",
}

_CHUNK_THOUGHTS: dict[int, str] = {
    1: "First documents split into passages — preparing the corpus for LLM extraction…",
    25: "Chunking a quarter of the corpus — sizing text for the extraction model",
    50: "Half the corpus chunked — passages ready for entity mining",
    75: "Most documents chunked — almost ready to start extraction",
    100: "All documents chunked into text units",
}

_SUMMARIZE_DESC_THOUGHTS: dict[int, str] = {
    1: "Polishing the first entity descriptions — making nodes readable for global search…",
    25: "Descriptions taking shape — summarizing what each entity means in context",
    50: "Half the entities described — relationship wording getting clearer",
    75: "Most descriptions drafted — tightening language for retrieval",
    100: "Entity and relationship descriptions complete",
}

_COMMUNITY_THOUGHTS: dict[int, str] = {
    1: "Summarizing the first community themes — finding the story in each cluster…",
    25: "Community narratives emerging — each cluster getting a thematic headline",
    50: "Half the communities summarized — global-search reports taking form",
    75: "Most community summaries drafted — almost ready for embedding",
    100: "Community summaries complete",
}

_EMBED_THOUGHTS: dict[int, str] = {
    1: "First embeddings landing — vectorizing descriptions for semantic retrieval…",
    25: "Embedding pipeline warming up — vectors stored for global search",
    50: "Half the entity vectors written — index filling in",
    75: "Most embeddings stored — finishing the vector index",
    100: "All embeddings stored — index ready",
}


@dataclass(frozen=True)
class GraphragLogEvent:
    kind: Literal["workflow_started", "workflow_completed", "progress"]
    workflow: str
    stage: StageId
    percent: int
    """Concise line for progress bar / log view."""
    label: str
    current: int | None = None
    total: int | None = None
    """Narrative theater card title; None → skip activity feed for this tick."""
    activity_label: str | None = None
    activity_detail: str | None = None


def _pct_in_workflow(workflow: str, current: int, total: int) -> int:
    lo, hi = WORKFLOW_PCT.get(workflow, (15, 90))
    if total <= 0:
        return lo
    frac = max(0.0, min(1.0, current / total))
    return int(lo + (hi - lo) * frac)


def _percent_complete(current: int, total: int) -> int:
    if total <= 0:
        return 0
    if current >= total:
        return 100
    return max(1, min(99, int(100 * current / total)))


def _milestone_key(current: int, total: int) -> int | None:
    """Return a stable milestone id when an activity card should fire."""
    if total <= 0:
        return None
    if current <= 1:
        return 1
    if current >= total:
        return 100
    pct = _percent_complete(current, total)
    for threshold in (25, 50, 75, 90):
        prev_pct = _percent_complete(current - 1, total)
        if prev_pct < threshold <= pct:
            return threshold
    return None


def _thought_for_milestone(thoughts: dict[int, str], milestone: int, *, current: int, total: int) -> str:
    if milestone in thoughts:
        return thoughts[milestone]
    return f"Progress — {current:,} of {total:,} complete"


def _progress_narrative(
    progress_kind: str,
    current: int,
    total: int,
) -> tuple[str, str | None, str | None]:
    """Return (progress_label, activity_label|None, activity_detail|None)."""
    workflow = _PROGRESS_KIND_WORKFLOW.get(progress_kind, progress_kind)
    pct = _percent_complete(current, total)
    milestone = _milestone_key(current, total)

    unit = "documents" if progress_kind in ("chunk", "extract") else "items"
    progress_label = f"{progress_kind.replace('_', ' ').title()} — {current}/{total} {unit}"

    if milestone is None:
        return progress_label, None, None

    if progress_kind == "extract":
        thought = _thought_for_milestone(_EXTRACT_THOUGHTS, milestone, current=current, total=total)
    elif progress_kind == "chunk":
        thought = _thought_for_milestone(_CHUNK_THOUGHTS, milestone, current=current, total=total)
    elif progress_kind == "summarize_descriptions":
        thought = _thought_for_milestone(_SUMMARIZE_DESC_THOUGHTS, milestone, current=current, total=total)
    elif progress_kind == "summarize_communities":
        thought = _thought_for_milestone(_COMMUNITY_THOUGHTS, milestone, current=current, total=total)
    elif progress_kind == "embeddings":
        thought = _thought_for_milestone(_EMBED_THOUGHTS, milestone, current=current, total=total)
    else:
        thought = f"Working through {workflow.replace('_', ' ')} — about {pct}% done"

    detail = f"{current:,} / {total:,} {unit} · ~{pct}%"
    return progress_label, thought, detail


def _progress_event(
    *,
    progress_kind: str,
    workflow: str,
    stage: StageId,
    current: int,
    total: int,
) -> GraphragLogEvent:
    pct = _pct_in_workflow(workflow, current, total)
    progress_label, activity_label, activity_detail = _progress_narrative(
        progress_kind, current, total
    )
    return GraphragLogEvent(
        kind="progress",
        workflow=workflow,
        stage=stage,
        percent=pct,
        label=progress_label,
        current=current,
        total=total,
        activity_label=activity_label,
        activity_detail=activity_detail,
    )


def parse_graphrag_log_line(line: str) -> GraphragLogEvent | None:
    text = line.strip()
    if not text:
        return None

    m = _WORKFLOW_STARTED.search(text)
    if m:
        wf = m.group(1)
        stage = WORKFLOW_STAGE.get(wf, "building_graph")
        lo, _hi = WORKFLOW_PCT.get(wf, (15, 90))
        label = WORKFLOW_NARRATIVE_START.get(wf, wf.replace("_", " "))
        return GraphragLogEvent(
            kind="workflow_started",
            workflow=wf,
            stage=stage,
            percent=lo,
            label=label,
            activity_label=label,
        )

    m = _WORKFLOW_COMPLETED.search(text)
    if m:
        wf = m.group(1)
        stage = WORKFLOW_STAGE.get(wf, "building_graph")
        _lo, hi = WORKFLOW_PCT.get(wf, (15, 90))
        label = WORKFLOW_NARRATIVE_DONE.get(wf, f"{wf.replace('_', ' ')} — done")
        return GraphragLogEvent(
            kind="workflow_completed",
            workflow=wf,
            stage=stage,
            percent=hi,
            label=label,
            activity_label=label,
        )

    m = _EXTRACT_PROGRESS.search(text)
    if m:
        current, total = int(m.group(1)), int(m.group(2))
        return _progress_event(
            progress_kind="extract",
            workflow="extract_graph",
            stage="building_graph",
            current=current,
            total=total,
        )

    m = _CHUNK_PROGRESS.search(text)
    if m:
        current, total = int(m.group(1)), int(m.group(2))
        return _progress_event(
            progress_kind="chunk",
            workflow="create_base_text_units",
            stage="graphrag_indexing",
            current=current,
            total=total,
        )

    m = _SUMMARIZE_PROGRESS.search(text)
    if m:
        current, total = int(m.group(1)), int(m.group(2))
        return _progress_event(
            progress_kind="summarize_descriptions",
            workflow="summarize_descriptions",
            stage="building_graph",
            current=current,
            total=total,
        )

    m = _COMMUNITY_PROGRESS.search(text)
    if m:
        current, total = int(m.group(1)), int(m.group(2))
        return _progress_event(
            progress_kind="summarize_communities",
            workflow="summarize_communities",
            stage="extracting_graph",
            current=current,
            total=total,
        )

    m = _EMBED_PROGRESS.search(text)
    if m:
        current, total = int(m.group(1)), int(m.group(2))
        return _progress_event(
            progress_kind="embeddings",
            workflow="generate_text_embeddings",
            stage="extracting_graph",
            current=current,
            total=total,
        )

    return None
