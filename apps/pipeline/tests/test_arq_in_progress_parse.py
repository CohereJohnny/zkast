"""Tests for arq in-progress suffix parsing."""

from app.job_redis import parse_arq_in_progress_suffix, _parse_arq_in_progress


def test_parse_graphrag_job_id_with_uuid():
    job_id, func = parse_arq_in_progress_suffix(
        "graphrag:8df70ac3-bc9a-421b-8d2b-9caa0ce27bac"
    )
    assert job_id == "graphrag:8df70ac3-bc9a-421b-8d2b-9caa0ce27bac"
    assert func is None


def test_parse_graphrag_job_id_with_function_suffix():
    job_id, func = parse_arq_in_progress_suffix(
        "graphrag:idx-1:run_graphrag_index_job"
    )
    assert job_id == "graphrag:idx-1"
    assert func == "run_graphrag_index_job"


def test_parse_document_stage_suffix():
    job_id, func = parse_arq_in_progress_suffix("abc-123:parse")
    assert job_id == "abc-123"
    assert func == "parse"


def test_parse_arq_in_progress_map_includes_graphrag():
    out = _parse_arq_in_progress(["graphrag:8df70ac3-bc9a-421b-8d2b-9caa0ce27bac"])
    assert "graphrag:8df70ac3-bc9a-421b-8d2b-9caa0ce27bac" in out
