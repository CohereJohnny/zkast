"""Sprint 5b: ingestion heartbeats, log table, merge audit, snapshot reviews."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007_ingestion_observability"
down_revision = "0006_graph_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # B1: heartbeat column for the worker-crash reconciler.
    op.add_column(
        "ingestion_runs",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_ingestion_runs_status_heartbeat",
        "ingestion_runs",
        ["status", "last_heartbeat_at"],
    )

    # A3: durable per-run log for the streaming console + post-mortem.
    op.create_table(
        "ingestion_run_logs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "ingestion_run_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", JSONB(), nullable=True),
        sa.CheckConstraint(
            "level IN ('info','warning','error')",
            name="ck_ingestion_run_logs_level",
        ),
    )
    op.create_index(
        "ix_ingestion_run_logs_run_ts",
        "ingestion_run_logs",
        ["ingestion_run_id", sa.text("ts DESC")],
    )
    op.create_index(
        "ix_ingestion_run_logs_level_ts",
        "ingestion_run_logs",
        ["level", sa.text("ts DESC")],
    )

    # D1: capture pre-merge provenance so unmerge can restore the victim row.
    op.create_table(
        "merge_audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),  # 'entity' | 'note'
        sa.Column("survivor_id", sa.Uuid(), nullable=False),
        sa.Column("victim_id", sa.Uuid(), nullable=False),
        sa.Column("victim_payload", JSONB(), nullable=False),
        sa.Column("survivor_before", JSONB(), nullable=False),
        sa.Column("victim_provenance", JSONB(), nullable=False),
        sa.Column("incident_relationships", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('entity','note')", name="ck_merge_audit_kind"),
    )
    op.create_index(
        "ix_merge_audit_survivor",
        "merge_audit_log",
        ["survivor_id", sa.text("created_at DESC")],
    )

    # D4: snapshot review decisions (Sprint 7 surfaces the workflow; we ship
    # the API + table now so chat citations can refer to reviewed snapshots).
    op.create_table(
        "snapshot_reviews",
        sa.Column(
            "snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("graph_snapshots.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('approved','rejected')",
            name="ck_snapshot_reviews_decision",
        ),
    )

    # Seed pipeline_settings defaults for streaming + parallelism. Use
    # jsonb_set with create_missing=true so existing workspaces gain the
    # defaults without clobbering bespoke overrides.
    op.execute(
        """
        UPDATE workspaces SET pipeline_settings = (
          jsonb_set(
            jsonb_set(
              COALESCE(pipeline_settings, '{}'::jsonb),
              '{graph_extract_concurrency}',
              to_jsonb(COALESCE(
                (pipeline_settings->>'graph_extract_concurrency')::int, 4)),
              true
            ),
            '{notes_llm_streaming}',
            to_jsonb(COALESCE(
              (pipeline_settings->>'notes_llm_streaming')::boolean, true)),
            true
          )
        )
        """
    )


def downgrade() -> None:
    op.drop_table("snapshot_reviews")
    op.drop_index("ix_merge_audit_survivor", table_name="merge_audit_log")
    op.drop_table("merge_audit_log")
    op.drop_index("ix_ingestion_run_logs_level_ts", table_name="ingestion_run_logs")
    op.drop_index("ix_ingestion_run_logs_run_ts", table_name="ingestion_run_logs")
    op.drop_table("ingestion_run_logs")
    op.drop_index("ix_ingestion_runs_status_heartbeat", table_name="ingestion_runs")
    op.drop_column("ingestion_runs", "last_heartbeat_at")
