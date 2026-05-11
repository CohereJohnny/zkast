"""ApiKey storage + default pipeline_settings merge.

Constraints (documented):
- api_keys.kind is application-defined text (P0: llm_cohere, target_neo4j, target_age).
- At most one llm_cohere key per workspace (partial unique index).
- encrypted_secret: AES-256-GCM payload (nonce || ciphertext || tag), base64-encoded by the app.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002_api_keys"
down_revision = "0001_init"
branch_labels = None
depends_on = None

# Defaults merged under existing workspace.pipeline_settings (user JSON wins on key clash).
PIPELINE_SETTINGS_DEFAULTS: dict[str, object] = {
    "chunk_size": 512,
    "max_notes_per_document": 500,
    "language": "en",
    "default_llm_provider": "cohere",
    "small_model": "command-r7b-12-2024",
    "large_model": "command-a-plus-05-2026",
    "embed_model": "embed-v4.0",
    "rerank_model": "rerank-v4.0-fast",
    "include_provenance_subgraph_default": True,
}


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_workspace_id", "api_keys", ["workspace_id"])
    op.create_index(
        "uq_api_keys_workspace_llm_cohere",
        "api_keys",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'llm_cohere'"),
    )

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, pipeline_settings FROM workspaces")).mappings().all()
    for row in rows:
        existing = row["pipeline_settings"]
        if existing is None:
            merged = dict(PIPELINE_SETTINGS_DEFAULTS)
        elif isinstance(existing, dict):
            merged = {**PIPELINE_SETTINGS_DEFAULTS, **existing}
        else:
            merged = dict(PIPELINE_SETTINGS_DEFAULTS)
        conn.execute(
            sa.text("UPDATE workspaces SET pipeline_settings = CAST(:merged AS jsonb) WHERE id = :id"),
            {"merged": json.dumps(merged), "id": row["id"]},
        )


def downgrade() -> None:
    op.drop_index("uq_api_keys_workspace_llm_cohere", table_name="api_keys")
    op.drop_index("ix_api_keys_workspace_id", table_name="api_keys")
    op.drop_table("api_keys")
