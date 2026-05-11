"""Optional integration smoke: synthetic episode through Graphiti + FalkorDB."""

from __future__ import annotations

import os

import pytest

from app.config import get_settings
from app.graphiti_factory import graphiti_for_workspace, run_synthetic_episode_smoke


@pytest.mark.asyncio
async def test_graphiti_synthetic_episode_smoke() -> None:
    if os.getenv("ZKAST_GRAPHITI_SMOKE") != "1":
        pytest.skip("Set ZKAST_GRAPHITI_SMOKE=1 to run live Graphiti smoke")
    if not os.getenv("COHERE_API_KEY"):
        pytest.skip("COHERE_API_KEY not set")

    try:
        settings = get_settings()
    except Exception:
        pytest.skip("pipeline settings/env not loaded")

    ws = os.getenv("ZKAST_TEST_WORKSPACE_ID", "00000000-0000-4000-8000-000000000002")
    graphiti = await graphiti_for_workspace(settings, ws)
    try:
        await run_synthetic_episode_smoke(graphiti, group_id=ws)
    finally:
        await graphiti.close()
