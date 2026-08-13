"""Tests for orphaned GraphRAG job reconciliation."""

from unittest.mock import AsyncMock, patch

import pytest

from app.graphrag_reconcile import reconcile_stale_graphrag_indexes


@pytest.mark.asyncio
async def test_reconcile_marks_orphaned_running_index():
    redis = AsyncMock()
    redis.hgetall = AsyncMock(return_value={"status": "running", "workspace_id": "ws-1"})

    with patch(
        "app.graphrag_reconcile.list_active_graphrag_indexes",
        return_value=[{"id": "idx-1", "status": "running"}],
    ), patch("app.graphrag_reconcile.mark_failed") as mark_failed, patch(
        "app.graphrag_reconcile.job_hset",
        new=AsyncMock(),
    ), patch(
        "app.graphrag_reconcile.publish_job_event",
        new=AsyncMock(),
    ), patch(
        "app.graphrag_reconcile.record_log",
        new=AsyncMock(),
    ):
        n = await reconcile_stale_graphrag_indexes(
            redis,
            "postgresql://unused",
            arq_in_progress=[],
        )

    assert n == 1
    mark_failed.assert_called_once()
    assert mark_failed.call_args.kwargs["index_id"] == "idx-1"


@pytest.mark.asyncio
async def test_reconcile_skips_active_arq_job():
    redis = AsyncMock()

    with patch(
        "app.graphrag_reconcile.list_active_graphrag_indexes",
        return_value=[{"id": "idx-1", "status": "running"}],
    ), patch("app.graphrag_reconcile.mark_failed") as mark_failed:
        n = await reconcile_stale_graphrag_indexes(
            redis,
            "postgresql://unused",
            arq_in_progress=["graphrag:idx-1"],
        )

    assert n == 0
    mark_failed.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_restores_false_positive_failure():
    redis = AsyncMock()

    with patch(
        "app.graphrag_reconcile.list_active_graphrag_indexes",
        return_value=[{"id": "idx-1", "status": "failed"}],
    ), patch("app.graphrag_reconcile.mark_running") as mark_running, patch(
        "app.graphrag_reconcile.job_hset",
        new=AsyncMock(),
    ), patch("app.graphrag_reconcile.mark_failed") as mark_failed:
        n = await reconcile_stale_graphrag_indexes(
            redis,
            "postgresql://unused",
            arq_in_progress=["graphrag:idx-1"],
        )

    assert n == 0
    mark_running.assert_called_once()
    mark_failed.assert_not_called()
