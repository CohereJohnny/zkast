"""Regression tests for arq per-stage job timeouts.

The arq default ``job_timeout`` is 300s. ``extract_graph`` regularly exceeds
that on 20-page PDFs while Graphiti retries edge-timestamp extraction
(TD-010), so the worker must apply per-function overrides via
``arq.worker.func()`` and use generous budgets.

These tests pin the contract so future refactors don't silently regress to
arq's default and re-introduce the 5-minute mystery cancel.
"""

from __future__ import annotations

import pytest


def test_worker_settings_uses_per_function_timeouts() -> None:
    """Each pipeline stage must declare its own timeout via ``arq_func``.

    A bare function in ``functions = [...]`` falls back to arq's 300s
    default which is too tight for ``extract_graph``.
    """
    from arq.worker import Function

    from app.tasks import WorkerSettings

    assert len(WorkerSettings.functions) >= 3
    by_name: dict[str, Function] = {}
    for entry in WorkerSettings.functions:
        # ``arq_func`` returns an ``arq.worker.Function`` instance; bare
        # coroutines would not, and that's the regression we guard against.
        assert isinstance(entry, Function), (
            f"WorkerSettings.functions entry {entry!r} is not wrapped with "
            "arq_func(); arq's 300s default will be used and CancelledError "
            "will appear as cancelled_by_job_timeout."
        )
        by_name[entry.name] = entry

    assert "parse_document" in by_name
    assert "generate_atomic_notes" in by_name
    assert "extract_graph" in by_name

    # Concrete budgets — adjust deliberately. The graph stage must be the
    # most generous because of Graphiti's per-edge retry storm.
    assert by_name["parse_document"].timeout_s >= 300
    assert by_name["generate_atomic_notes"].timeout_s >= 600
    assert by_name["extract_graph"].timeout_s >= 1_800


def test_classify_cancel_reason_within_timeout_window() -> None:
    """When CancelledError fires close to the per-stage budget, label it as a
    job_timeout (not a worker shutdown) so operators investigate the right
    thing.
    """
    from app.tasks import (
        TIMEOUT_GRAPH_S,
        TIMEOUT_CLASSIFY_WINDOW_S,
        _classify_cancel_reason,
    )

    reason, extra = _classify_cancel_reason(
        "extracting_graph", TIMEOUT_GRAPH_S - 5
    )
    assert "cancelled_by_job_timeout" in reason
    assert extra["timeout_s"] == TIMEOUT_GRAPH_S
    assert extra["elapsed_s"] == pytest.approx(TIMEOUT_GRAPH_S - 5, rel=0.01)


def test_classify_cancel_reason_far_from_timeout() -> None:
    """A cancel that fires within the first few seconds is almost certainly
    a SIGTERM, not a timeout.
    """
    from app.tasks import _classify_cancel_reason

    reason, extra = _classify_cancel_reason("parsing", 2.5)
    assert reason == "cancelled_by_worker_shutdown"
    assert extra["elapsed_s"] == pytest.approx(2.5)


def test_reconciler_cron_fires_once_per_minute() -> None:
    """The reconciler must use ``cron(..., second=0)`` and not
    ``minute=set(range(60))`` which produced a startup burst of duplicate
    runs every ~500ms.
    """
    from app.tasks import WorkerSettings

    assert WorkerSettings.cron_jobs, "WorkerSettings.cron_jobs is empty"
    spec = WorkerSettings.cron_jobs[0]
    # arq stores the minute matcher on the CronJob.minute attribute.
    # We require it to be None (= every minute) rather than a set, so the
    # next-run computation is unambiguous.
    minute = getattr(spec, "minute", None)
    assert minute is None, (
        f"reconcile_stuck_documents cron has minute={minute!r}; expected None "
        "so arq fires it cleanly at second=0 of every minute."
    )
    # ``second`` must be pinned at 0 so we don't fire every second.
    second = getattr(spec, "second", None)
    assert second == 0 or second == {0}, f"unexpected second matcher: {second!r}"
