"""A-MEM enrichment — body immutability and derivation fields."""

from __future__ import annotations

import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.amem_enrich import enrich_notes_amem_batch
from app.notes_repo import fetch_note, insert_note, patch_note_derivations

DEFAULT_WS = "00000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def _mock_completion(payload: dict) -> MagicMock:
    msg = MagicMock()
    msg.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.mark.asyncio
async def test_enrich_perserves_body_and_sets_derivations() -> None:
    db = os.environ["DATABASE_URL"]
    nid = str(uuid.uuid4())
    insert_note(
        db,
        note_id=nid,
        workspace_id=DEFAULT_WS,
        title="North note",
        body="Immutable body text for enrich test.",
        tags=["seed"],
        origin="manual",
        created_by_user_id=None,
        episode_ids=[],
        is_user_edited=False,
        agent_id=None,
    )
    before = fetch_note(db, workspace_id=DEFAULT_WS, note_id=nid)
    assert before is not None

    payload = {
        "items": [
            {
                "note_id": nid,
                "memory_keywords": ["concept", "memory"],
                "memory_context": "A short contextual summary.",
                "tags": ["north"],
            }
        ]
    }

    with patch("app.amem_enrich.AsyncOpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_mock_completion(payload))
        mock_client_cls.return_value = mock_client

        result = await enrich_notes_amem_batch(
            api_key="test-key",
            model="command-r7b-12-2024",
            database_url=db,
            workspace_id=DEFAULT_WS,
            note_ids=[nid],
        )

    assert result.enriched == 1
    after = fetch_note(db, workspace_id=DEFAULT_WS, note_id=nid)
    assert after is not None
    assert after["body"] == before["body"]
    assert after.get("memory_context")
    assert "concept" in (after.get("memory_keywords") or [])
    assert "north" in (after.get("tags") or [])
    assert after.get("dreaming_touched_at") is None


def test_patch_note_derivations_dreaming_touch_only_when_requested() -> None:
    db = os.environ["DATABASE_URL"]
    nid = str(uuid.uuid4())
    insert_note(
        db,
        note_id=nid,
        workspace_id=DEFAULT_WS,
        title="Touch test",
        body="Body",
        tags=[],
        origin="manual",
        created_by_user_id=None,
        episode_ids=[],
        is_user_edited=False,
    )
    patch_note_derivations(
        db,
        workspace_id=DEFAULT_WS,
        note_id=nid,
        memory_context="ctx",
        mark_dreaming_touch=False,
    )
    row = fetch_note(db, workspace_id=DEFAULT_WS, note_id=nid)
    assert row is not None
    assert row.get("dreaming_touched_at") is None
