"""Graph snapshots: immutable freeze of working graph (entities, relationships, notes)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006_graph_snapshots"
down_revision = "0005_notes_graph"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stats", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("workspace_id", "name", name="uq_graph_snapshots_workspace_name"),
    )
    op.execute(
        "CREATE INDEX ix_graph_snapshots_workspace_created ON graph_snapshots (workspace_id, created_at DESC)",
    )

    # Frozen rows: source_* ids are copies at freeze time (no FK to live rows — survives entity deletes).
    op.create_table(
        "snapshot_entities",
        sa.Column(
            "snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("graph_snapshots.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("source_entity_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
    )
    op.create_index("ix_snapshot_entities_snapshot", "snapshot_entities", ["snapshot_id"])

    op.create_table(
        "snapshot_relationships",
        sa.Column(
            "snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("graph_snapshots.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("source_relationship_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
    )
    op.create_index("ix_snapshot_relationships_snapshot", "snapshot_relationships", ["snapshot_id"])

    op.create_table(
        "snapshot_notes",
        sa.Column(
            "snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("graph_snapshots.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("source_note_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
    )
    op.create_index("ix_snapshot_notes_snapshot", "snapshot_notes", ["snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_snapshot_notes_snapshot", table_name="snapshot_notes")
    op.drop_table("snapshot_notes")
    op.drop_index("ix_snapshot_relationships_snapshot", table_name="snapshot_relationships")
    op.drop_table("snapshot_relationships")
    op.drop_index("ix_snapshot_entities_snapshot", table_name="snapshot_entities")
    op.drop_table("snapshot_entities")
    op.execute("DROP INDEX IF EXISTS ix_graph_snapshots_workspace_created")
    op.drop_table("graph_snapshots")
