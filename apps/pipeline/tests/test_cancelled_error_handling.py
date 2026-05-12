"""B2.5 — verify ``asyncio.CancelledError`` is caught, not silently re-raised.

The actual production handler in :mod:`app.tasks` is heavy (touches Postgres
+ Redis + arq). This module pins the contract: ``CancelledError`` must be
caught before the generic ``except Exception`` so the worker can mark the
document failed with a recoverable reason before re-raising for arq.

Python 3.8+ made ``CancelledError`` a ``BaseException`` subclass — this test
makes the assumption explicit so future regressions are loud.
"""

from __future__ import annotations

import asyncio
import sys

import pytest


def test_cancelled_error_is_base_exception_in_py38plus() -> None:
    assert sys.version_info >= (3, 8)
    assert issubclass(asyncio.CancelledError, BaseException)
    assert not issubclass(asyncio.CancelledError, Exception)


def test_bare_except_exception_does_not_catch_cancelled() -> None:
    async def task() -> None:
        try:
            raise asyncio.CancelledError()
        except Exception:  # noqa: BLE001
            pytest.fail("CancelledError should not be caught by `except Exception`")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(task())


def test_explicit_handler_catches_then_reraises() -> None:
    """Mirrors the pattern used in ``parse_document`` / ``generate_atomic_notes``
    / ``extract_graph``: catch CancelledError, mark failed, re-raise.
    """
    marked: list[str] = []

    async def task() -> None:
        try:
            raise asyncio.CancelledError()
        except asyncio.CancelledError:
            marked.append("failed:cancelled_by_worker_shutdown")
            raise
        except Exception:  # noqa: BLE001
            marked.append("failed:other")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(task())
    assert marked == ["failed:cancelled_by_worker_shutdown"]
