"""Bump default Cohere chat/embed/rerank model IDs on all workspaces."""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0003_pipeline_models"
down_revision = "0002_api_keys"
branch_labels = None
depends_on = None

NEW_MODEL_IDS: dict[str, str] = {
    "small_model": "command-r7b-12-2024",
    "large_model": "command-a-plus-05-2026",
    "embed_model": "embed-v4.0",
    "rerank_model": "rerank-v4.0-fast",
}

PREVIOUS_MODEL_IDS: dict[str, str] = {
    "small_model": "command-r",
    "large_model": "command-r-plus",
    "embed_model": "embed-english-v3.0",
    "rerank_model": "rerank-english-v3.0",
}


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE workspaces SET pipeline_settings = pipeline_settings || CAST(:patch AS jsonb)"
        ),
        {"patch": json.dumps(NEW_MODEL_IDS)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE workspaces SET pipeline_settings = pipeline_settings || CAST(:patch AS jsonb)"
        ),
        {"patch": json.dumps(PREVIOUS_MODEL_IDS)},
    )
