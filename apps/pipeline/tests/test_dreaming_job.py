"""Dreaming worker unit tests (mocked LLM + embedder)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import dreaming
from app.dreaming import DREAM_JOB_STATUS_SUCCEEDED, run_dreaming_job


def _note(nid: str, title: str = "T", body: str = "B") -> dict:
    return {
        "id": nid,
        "title": title,
        "body": body,
        "tags": [],
        "memory_context": None,
    }


@pytest.mark.asyncio
async def test_run_dreaming_job_records_stats_and_succeeds() -> None:
    n1, n2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
    notes = [_note(n1), _note(n2)]
    job_id = "job-1"
    finalize_args: dict = {}

    async def fake_embed_batch(_texts):
        return [[1.0, 0.0], [0.0, 1.0]]

    llm_response = MagicMock()
    llm_response.choices = [
        MagicMock(
            message=MagicMock(
                content=(
                    '{"should_link": true, "link_target_note_id": "'
                    + n2
                    + '", "link_kind": "related", "link_reason": "similar", '
                    '"neighbor_context_update": "ctx", "neighbor_tag_additions": ["tag1"]}'
                )
            )
        )
    ]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=llm_response)

    def fake_finalize(db, *, job_id: str, status: str, stats=None, failure_reason=None):
        finalize_args.update(
            job_id=job_id,
            status=status,
            stats=stats or {},
            failure_reason=failure_reason,
        )

    before = _note(n2, "T", "B")
    after = {**before, "memory_context": "ctx", "tags": ["tag1"]}

    with (
        patch.object(dreaming, "get_settings", return_value=SimpleNamespace()),
        patch.object(dreaming, "resolve_cohere_api_key", return_value="key"),
        patch.object(dreaming, "fetch_pipeline_settings", return_value={"large_model": "m", "embed_model": "e"}),
        patch.object(dreaming, "insert_dream_job", return_value=job_id),
        patch.object(dreaming, "finalize_dream_job", side_effect=fake_finalize),
        patch.object(dreaming, "list_notes", return_value=(notes, 2)),
        patch.object(dreaming, "CohereEmbedder") as embed_cls,
        patch.object(dreaming, "AsyncOpenAI", return_value=mock_client),
        patch.object(dreaming, "add_note_link", return_value={"id": "link-1"}),
        patch.object(dreaming, "insert_dream_mutation"),
        patch.object(dreaming, "patch_note_derivations"),
        patch.object(dreaming, "append_evolution_history"),
        patch.object(dreaming, "fetch_note", side_effect=[before, after]),
        patch.object(dreaming, "upsert_amem_embeddings_for_notes", new_callable=AsyncMock) as reindex,
    ):
        embed_cls.return_value.create_batch = AsyncMock(side_effect=fake_embed_batch)
        await run_dreaming_job(
            {"database_url": "postgresql://stub"},
            workspace_id="ws",
            agent_id="agent",
            job_id=job_id,
        )

    assert finalize_args["status"] == DREAM_JOB_STATUS_SUCCEEDED
    stats = finalize_args["stats"]
    assert stats["pairs_considered"] >= 1
    assert stats["links_added"] == 1
    assert stats["neighbors_updated"] == 1
    assert stats["embeddings_refreshed"] >= 1
    assert stats["notes_considered"] == 2
    reindex.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_dreaming_job_not_enough_notes() -> None:
    finalize_args: dict = {}

    def fake_finalize(db, *, job_id: str, status: str, stats=None, failure_reason=None):
        finalize_args.update(status=status, stats=stats)

    with (
        patch.object(dreaming, "get_settings", return_value=SimpleNamespace()),
        patch.object(dreaming, "resolve_cohere_api_key", return_value="key"),
        patch.object(dreaming, "fetch_pipeline_settings", return_value={}),
        patch.object(dreaming, "finalize_dream_job", side_effect=fake_finalize),
        patch.object(dreaming, "list_notes", return_value=([_note("only")], 1)),
    ):
        await run_dreaming_job(
            {"database_url": "postgresql://stub"},
            workspace_id="ws",
            agent_id="agent",
            job_id="job-2",
        )

    assert finalize_args["status"] == DREAM_JOB_STATUS_SUCCEEDED
    assert finalize_args["stats"].get("message") == "not_enough_notes"
