"""Tests for GraphRAG indexing-engine.log parsing."""

from app.graphrag_log_progress import parse_graphrag_log_line


def test_parse_extract_graph_progress_milestone():
    ev = parse_graphrag_log_line(
        "2026-06-03 04:11:59.0233 - INFO - graphrag.logger.progress - extract graph progress: 100/200"
    )
    assert ev is not None
    assert ev.kind == "progress"
    assert ev.workflow == "extract_graph"
    assert ev.current == 100
    assert ev.total == 200
    assert ev.activity_label is not None
    assert "Halfway" in ev.activity_label or "half" in ev.activity_label.lower()
    assert ev.activity_detail is not None


def test_parse_extract_graph_progress_skips_non_milestone():
    ev = parse_graphrag_log_line(
        "2026-06-03 04:11:59.0233 - INFO - graphrag.logger.progress - extract graph progress: 47/200"
    )
    assert ev is not None
    assert ev.activity_label is None
    assert "47/200" in ev.label


def test_parse_workflow_started_narrative():
    ev = parse_graphrag_log_line(
        "2026-06-03 04:02:55.0854 - INFO - graphrag.index.workflows.create_base_text_units - Workflow started: create_base_text_units"
    )
    assert ev is not None
    assert ev.kind == "workflow_started"
    assert ev.activity_label is not None
    assert "chunk" in ev.activity_label.lower() or "passage" in ev.activity_label.lower()


def test_parse_workflow_completed_narrative():
    ev = parse_graphrag_log_line(
        "2026-06-03 04:02:55.0832 - INFO - graphrag.api.index - Workflow load_input_documents completed successfully"
    )
    assert ev is not None
    assert ev.kind == "workflow_completed"
    assert "Corpus loaded" in (ev.activity_label or "")


def test_parse_summarize_descriptions_milestone():
    ev = parse_graphrag_log_line(
        "2026-06-03 04:47:57.0729 - INFO - graphrag.logger.progress - Summarize entity/relationship description progress: 1/2026"
    )
    assert ev is not None
    assert ev.workflow == "summarize_descriptions"
    assert ev.activity_label is not None
    assert "Polishing" in ev.activity_label or "description" in ev.activity_label.lower()
