"""Documents, ingestion runs, episodes, upload idempotency."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_documents_ingestion"
down_revision = "0003_pipeline_models"
branch_labels = None
depends_on = None

DOC_STATUSES = (
    "queued",
    "parsing",
    "generating_notes",
    "extracting_graph",
    "building_graph",
    "ready",
    "failed",
)

RUN_STATUSES = ("running", "succeeded", "failed", "cancelled")

EPISODE_KINDS = ("pdf_chunk", "manual_text")


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "replaces_document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in DOC_STATUSES)})",
            name="ck_documents_status",
        ),
        sa.CheckConstraint("mime_type = 'application/pdf'", name="ck_documents_mime_pdf"),
        sa.UniqueConstraint("workspace_id", "checksum", name="uq_documents_workspace_checksum"),
    )
    op.execute(
        "CREATE INDEX ix_documents_workspace_created ON documents (workspace_id, created_at DESC)",
    )
    op.create_index("ix_documents_workspace_status", "documents", ["workspace_id", "status"])

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("llm_provider", sa.Text(), nullable=False),
        sa.Column("llm_model_small", sa.Text(), nullable=False),
        sa.Column("llm_model_large", sa.Text(), nullable=False),
        sa.Column("stats", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in RUN_STATUSES)})",
            name="ck_ingestion_runs_status",
        ),
    )
    op.execute(
        "CREATE INDEX ix_ingestion_runs_document_started ON ingestion_runs (document_id, started_at DESC)",
    )

    op.create_table(
        "episodes",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_run_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"kind IN ({', '.join(repr(k) for k in EPISODE_KINDS)})",
            name="ck_episodes_kind",
        ),
        sa.UniqueConstraint("document_id", "sequence", name="uq_episodes_document_sequence"),
    )
    op.execute(
        "CREATE INDEX ix_episodes_workspace_created ON episodes (workspace_id, created_at DESC)",
    )

    op.create_table(
        "upload_idempotency",
        sa.Column("key", sa.Text(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_upload_idempotency_created", "upload_idempotency", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_upload_idempotency_created", table_name="upload_idempotency")
    op.drop_table("upload_idempotency")
    op.execute("DROP INDEX IF EXISTS ix_episodes_workspace_created")
    op.drop_table("episodes")
    op.execute("DROP INDEX IF EXISTS ix_ingestion_runs_document_started")
    op.drop_table("ingestion_runs")
    op.drop_index("ix_documents_workspace_status", table_name="documents")
    op.execute("DROP INDEX IF EXISTS ix_documents_workspace_created")
    op.drop_table("documents")
