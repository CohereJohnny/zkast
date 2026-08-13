"""GraphRAG index jobs integrate with the Redis job log channel."""

from unittest.mock import MagicMock, patch

from app.graphrag_tasks import graphrag_job_id
from app.job_redis import STAGE_LABELS, enrich_pipeline_jobs


def test_graphrag_job_id_format() -> None:
    assert graphrag_job_id("abc-123") == "graphrag:abc-123"


def test_enrich_graphrag_index_job_title() -> None:
    jobs = [
        {
            "job_id": "graphrag:idx-1",
            "workspace_id": "ws-1",
            "kind": "graphrag_index",
            "status": "running",
            "title": "GraphRAG: #industry-oil-and-gas",
            "progress": {"percent": 40, "stage": "graphrag_indexing"},
            "created_at": "2026-06-02T12:00:00+00:00",
        }
    ]
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = []
    with patch("app.job_redis.psycopg.connect", return_value=mock_conn):
        enriched = enrich_pipeline_jobs(
            "postgresql://unused",
            jobs,
            arq_in_progress=["graphrag:idx-1:run_graphrag_index_job"],
        )
    assert len(enriched) == 1
    row = enriched[0]
    assert row["title"] == "GraphRAG: #industry-oil-and-gas"
    assert row["stage"] == "graphrag_indexing"
    assert row["stage_label"] == STAGE_LABELS["graphrag_indexing"]
    assert row["worker_active"] is True
    assert row["percent"] == 40
