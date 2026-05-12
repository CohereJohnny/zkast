"""LLM note generation respects max_notes (mocked Cohere client)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.notes_llm import generate_notes_from_episodes


@pytest.mark.asyncio
async def test_respects_max_notes() -> None:
    episodes = [
        {"id": "e1", "text": "hello world " * 50, "page_start": 1, "page_end": 1, "sequence": 0},
    ]

    many_notes = [
        {"title": f"n{i}", "body": "b", "tags": [], "source_chunk_indices": [0]} for i in range(12)
    ]
    payload = json.dumps({"notes": many_notes, "suggested_links": []})

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock(message=MagicMock(content=payload))]

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

    with patch("app.notes_llm.AsyncOpenAI", return_value=mock_client):
        notes, links = await generate_notes_from_episodes(
            api_key="test-key",
            model="m",
            episodes=episodes,
            max_notes=3,
            streaming=False,
        )

    assert len(notes) == 3
    assert links == []
