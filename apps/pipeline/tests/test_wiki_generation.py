"""Unit tests for the LLM Wiki generation worker.

These tests cover the deterministic synthesis path: ``run_wiki_generation_job``
must drive the wiki repo through a predictable set of upserts, attach citation
rows, record audit mutations, and emit verbose pipeline-log lines when a Redis
context is provided. DB I/O is mocked out so the tests stay fast and
self-contained.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import wiki_generation
from app.wiki_generation import (
    WIKI_JOB_STATUS_FAILED,
    WIKI_JOB_STATUS_SUCCEEDED,
    run_wiki_generation_job,
)


def _note(nid: str, *, title: str, tags: list[str], agent_id: str | None = None) -> dict:
    return {
        "id": nid,
        "workspace_id": "ws",
        "agent_id": agent_id,
        "title": title,
        "body": f"Body for {title}.",
        "tags": tags,
        "memory_context": None,
        "memory_keywords": [],
        "origin": "generated",
    }


def _ws_space() -> dict:
    return {
        "id": "wiki-space-1",
        "workspace_id": "ws",
        "agent_id": None,
        "scope_kind": "workspace",
        "scope_target_id": None,
        "name": "Workspace wiki",
        "status": "empty",
        "settings": {},
    }


def _agent_space() -> dict:
    return {
        "id": "wiki-space-agent",
        "workspace_id": "ws",
        "agent_id": "agent-1",
        "scope_kind": "agent",
        "scope_target_id": "agent-1",
        "name": "Agent wiki",
        "status": "empty",
        "settings": {},
    }


def _page_upsert_factory():
    counter = {"n": 0}
    created: list[tuple[str, str, str]] = []

    def fake_upsert(_db, **kwargs):
        counter["n"] += 1
        page_id = f"page-{counter['n']}"
        created.append((page_id, kwargs.get("slug", ""), kwargs.get("page_type", "")))
        return page_id, "created"

    return fake_upsert, created


@pytest.mark.asyncio
async def test_run_wiki_generation_succeeds_with_no_notes() -> None:
    job_status: dict = {}

    def fake_job_status(_db, *, job_id, status, stats=None, failure_reason=None):
        job_status.update(job_id=job_id, status=status, stats=stats, failure_reason=failure_reason)

    space_status: dict = {}

    def fake_space_status(_db, *, space_id, status, mark_generated=False):
        space_status.update(space_id=space_id, status=status, mark_generated=mark_generated)

    with (
        patch.object(wiki_generation, "fetch_wiki_space", return_value=_ws_space()),
        patch.object(wiki_generation, "insert_wiki_job", return_value="job-1"),
        patch.object(wiki_generation, "update_wiki_job_status", side_effect=fake_job_status),
        patch.object(wiki_generation, "update_wiki_space_status", side_effect=fake_space_status),
        patch.object(wiki_generation, "fetch_notes_for_wiki", return_value=[]),
    ):
        await run_wiki_generation_job(
            {"database_url": "postgresql://stub"},
            workspace_id="ws",
            wiki_space_id="wiki-space-1",
            job_id="job-1",
        )

    assert job_status["status"] == WIKI_JOB_STATUS_SUCCEEDED
    assert (job_status["stats"] or {}).get("message") == "no_notes"
    assert space_status["status"] == "empty"
    assert space_status["mark_generated"] is True


@pytest.mark.asyncio
async def test_run_wiki_generation_creates_pages_and_citations() -> None:
    notes = [
        _note("note-1", title="Flood risk on John Doe farm", tags=["flood", "underwriting"]),
        _note("note-2", title="Recommended decline", tags=["underwriting"]),
        _note("note-3", title="Loss ratio", tags=["loss-ratio"]),
    ]
    upsert_calls, _created = _page_upsert_factory()
    mutations: list[dict] = []
    citations: list[dict] = []

    def fake_mut(_db, *, wiki_job_id, wiki_page_id, mutation_type, payload):
        mutations.append({
            "job": wiki_job_id,
            "page": wiki_page_id,
            "type": mutation_type,
            "payload": payload,
        })

    def fake_citations(_db, *, wiki_page_id, sources):
        citations.extend({"page": wiki_page_id, **s} for s in sources)
        return len(sources)

    listed_pages = [
        {"id": "p1", "slug": "synthesis", "title": "Workspace synthesis", "page_type": "synthesis"},
        {"id": "p2", "slug": "topic-flood", "title": "Topic: Flood", "page_type": "topic"},
    ]

    with (
        patch.object(wiki_generation, "fetch_wiki_space", return_value=_ws_space()),
        patch.object(wiki_generation, "insert_wiki_job", return_value="job-2"),
        patch.object(wiki_generation, "update_wiki_job_status"),
        patch.object(wiki_generation, "update_wiki_space_status"),
        patch.object(wiki_generation, "fetch_notes_for_wiki", return_value=notes),
        patch.object(wiki_generation, "upsert_wiki_page", side_effect=upsert_calls),
        patch.object(wiki_generation, "replace_wiki_page_sources", side_effect=fake_citations),
        patch.object(wiki_generation, "insert_wiki_mutation", side_effect=fake_mut),
        patch.object(wiki_generation, "list_wiki_pages", return_value=listed_pages),
    ):
        await run_wiki_generation_job(
            {"database_url": "postgresql://stub"},
            workspace_id="ws",
            wiki_space_id="wiki-space-1",
            job_id="job-2",
        )

    # We expect at minimum: one topic page per unique tag (flood, underwriting,
    # loss-ratio), one source-summary page per bucket, plus synthesis, index,
    # and changelog.
    page_types_touched = {m["payload"].get("page_type") for m in mutations}
    assert "topic" in page_types_touched
    assert "source_summary" in page_types_touched
    assert "synthesis" in page_types_touched
    assert "index" in page_types_touched
    assert "changelog" in page_types_touched
    # Citations include atomic notes for the topic pages.
    assert any(c.get("source_kind") == "atomic_note" for c in citations)


@pytest.mark.asyncio
async def test_run_wiki_generation_agent_scope_filters_notes() -> None:
    fetch_calls: list[dict] = []

    def fake_fetch(_db, *, workspace_id, agent_id=None, limit=200):
        fetch_calls.append({"workspace_id": workspace_id, "agent_id": agent_id, "limit": limit})
        return []

    with (
        patch.object(wiki_generation, "fetch_wiki_space", return_value=_agent_space()),
        patch.object(wiki_generation, "insert_wiki_job", return_value="job-3"),
        patch.object(wiki_generation, "update_wiki_job_status"),
        patch.object(wiki_generation, "update_wiki_space_status"),
        patch.object(wiki_generation, "fetch_notes_for_wiki", side_effect=fake_fetch),
    ):
        await run_wiki_generation_job(
            {"database_url": "postgresql://stub"},
            workspace_id="ws",
            wiki_space_id="wiki-space-agent",
            job_id="job-3",
        )

    assert fetch_calls, "expected fetch_notes_for_wiki to be called"
    assert fetch_calls[0]["agent_id"] == "agent-1"
    assert fetch_calls[0]["workspace_id"] == "ws"


@pytest.mark.asyncio
async def test_run_wiki_generation_emits_pipeline_logs_when_redis_present() -> None:
    notes = [
        _note("note-1", title="Note 1", tags=["alpha"]),
        _note("note-2", title="Note 2", tags=["beta"]),
    ]
    log_messages: list[str] = []

    async def capture_log(_redis, **kwargs):
        log_messages.append(str(kwargs.get("message") or ""))

    mock_redis = MagicMock()
    mock_redis.publish = AsyncMock()
    mock_redis.xadd = AsyncMock()
    mock_redis.hset = AsyncMock()
    mock_redis.expire = AsyncMock()

    upsert_calls, _ = _page_upsert_factory()

    with (
        patch.object(wiki_generation, "fetch_wiki_space", return_value=_ws_space()),
        patch.object(wiki_generation, "insert_wiki_job", return_value="job-4"),
        patch.object(wiki_generation, "update_wiki_job_status"),
        patch.object(wiki_generation, "update_wiki_space_status"),
        patch.object(wiki_generation, "fetch_notes_for_wiki", return_value=notes),
        patch.object(wiki_generation, "upsert_wiki_page", side_effect=upsert_calls),
        patch.object(wiki_generation, "replace_wiki_page_sources", return_value=2),
        patch.object(wiki_generation, "insert_wiki_mutation"),
        patch.object(wiki_generation, "list_wiki_pages", return_value=[]),
        patch.object(wiki_generation, "record_log", side_effect=capture_log),
        patch.object(wiki_generation, "record_metric", new_callable=AsyncMock),
        patch.object(wiki_generation, "publish_job_event", new_callable=AsyncMock),
        patch.object(wiki_generation, "job_hset", new_callable=AsyncMock),
    ):
        await run_wiki_generation_job(
            {"database_url": "postgresql://stub", "redis": mock_redis},
            workspace_id="ws",
            wiki_space_id="wiki-space-1",
            job_id="job-4",
        )

    joined = "\n".join(log_messages)
    assert "Wiki generation started" in joined
    assert "Loaded 2 note(s)" in joined
    assert "topic cluster" in joined
    assert "synthesis page" in joined
    assert "index page" in joined
    assert "Wiki generation complete" in joined


@pytest.mark.asyncio
async def test_run_wiki_generation_marks_failure_on_unhandled_exception() -> None:
    final_status: dict = {}

    def fake_status(_db, *, job_id, status, stats=None, failure_reason=None):
        final_status.update(job_id=job_id, status=status, failure_reason=failure_reason)

    space_status: dict = {}

    def fake_space(_db, *, space_id, status, mark_generated=False):
        space_status.update(status=status)

    def boom(_db, **_kw):
        raise RuntimeError("boom")

    with (
        patch.object(wiki_generation, "fetch_wiki_space", return_value=_ws_space()),
        patch.object(wiki_generation, "insert_wiki_job", return_value="job-5"),
        patch.object(wiki_generation, "update_wiki_job_status", side_effect=fake_status),
        patch.object(wiki_generation, "update_wiki_space_status", side_effect=fake_space),
        patch.object(wiki_generation, "fetch_notes_for_wiki", side_effect=boom),
    ):
        with pytest.raises(RuntimeError):
            await run_wiki_generation_job(
                {"database_url": "postgresql://stub"},
                workspace_id="ws",
                wiki_space_id="wiki-space-1",
                job_id="job-5",
            )

    assert final_status["status"] == WIKI_JOB_STATUS_FAILED
    assert "boom" in (final_status["failure_reason"] or "")
    assert space_status["status"] == "failed"
