"""GraphRAG index registry (composable evaluation harness).

Tracks a built Microsoft GraphRAG artifact set for one memory space + pipeline
configuration: status, artifact location, the ontology/provider used, and
summary stats. The batch index job (dedicated graphrag-worker) writes/updates
these rows. See specs/openspecs/composable-eval-harness.md and
spikes/ms-graphrag/README.md.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0022_graphrag_indexes"
down_revision = "0021_provider_api_keys"
branch_labels = None
depends_on = None

STATUSES = ("pending", "running", "ready", "failed")


def upgrade() -> None:
    op.create_table(
        "graphrag_indexes",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        # Memory space: an agent / Slack channel; NULL = whole-workspace graph.
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("configuration_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("artifact_uri", sa.Text(), nullable=True),
        sa.Column("ontology_name", sa.Text(), nullable=True),
        sa.Column("ontology_version", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False, server_default="cohere_compat"),
        sa.Column("embedding_dim", sa.Integer(), nullable=False, server_default="1536"),
        sa.Column("stats", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("job_id", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["configuration_id"], ["pipeline_configurations.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'ready', 'failed')",
            name="ck_graphrag_indexes_status",
        ),
    )
    op.create_index(
        "ix_graphrag_indexes_ws_agent",
        "graphrag_indexes",
        ["workspace_id", "agent_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_graphrag_indexes_ws_agent", table_name="graphrag_indexes")
    op.drop_table("graphrag_indexes")
