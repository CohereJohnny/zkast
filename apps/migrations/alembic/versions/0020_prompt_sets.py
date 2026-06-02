"""Versioned ontology / prompt-set store (composable evaluation harness).

A prompt set is the extraction stage's ontology + instructions: entity types,
edge types, edge-type map, and extraction guidance. It is versioned and
immutable once referenced; manual edits and auto-tuning produce new versions.
The DB is the runtime store of record; the built-in ``generic/v1`` baseline is
seeded from app/ontologies/generic_v1.yaml by prompt_sets_repo.ensure_builtin_seeded
(kept out of the migration so the YAML stays the single source of truth).

See specs/openspecs/composable-eval-harness.md.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0020_prompt_sets"
down_revision = "0019_pipeline_configurations"
branch_labels = None
depends_on = None

ORIGINS = ("generic", "manual", "auto")


def upgrade() -> None:
    op.create_table(
        "prompt_sets",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        # NULL workspace_id = global/built-in prompt set available to all workspaces.
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False, server_default="generic"),
        sa.Column("derived_from_version", sa.Text(), nullable=True),
        sa.Column("entity_types", JSONB(), nullable=False),
        sa.Column("edge_types", JSONB(), nullable=False),
        sa.Column("edge_type_map", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "origin IN ('generic', 'manual', 'auto')",
            name="ck_prompt_sets_origin",
        ),
    )
    op.create_index(
        "uq_prompt_sets_name_version",
        "prompt_sets",
        ["workspace_id", "name", "version"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_prompt_sets_name_version", table_name="prompt_sets")
    op.drop_table("prompt_sets")
