"""Sprint 5c: entity_evidence — char-offset source grounding from LangExtract.

Each row links a canonical entity back to a specific span inside an
episode (and therefore a page inside the source PDF). Lets the entity
detail panel show "this entity exists because the PDF said this" with
a quoted snippet and a one-click jump to the page.

Schema choices:
- ``char_start`` / ``char_end`` are stored as INTEGER (not BIGINT) — a
  single PDF episode body never exceeds a few thousand characters in
  practice, and 32-bit headroom keeps row size small.
- ``page`` is denormalized for fast filtering even though it's derivable
  from (document_id, char_start) and the original chunker output.
- ``quote`` is truncated to ~600 chars by the extractor before insert so
  blockquotes in the UI stay sane.
- ``method`` records which extractor produced the row (``langextract``
  today; reserved for ``glnier``, ``rebel``, etc. in the future).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008_entity_evidence"
down_revision = "0007_ingestion_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entity_id",
            sa.Uuid(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "episode_id",
            sa.Uuid(),
            sa.ForeignKey("episodes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("page", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False, server_default="langextract"),
        sa.Column(
            "attributes",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("char_end >= char_start", name="ck_entity_evidence_range"),
    )
    op.create_index(
        "ix_entity_evidence_entity",
        "entity_evidence",
        ["entity_id", "created_at"],
    )
    op.create_index(
        "ix_entity_evidence_document_page",
        "entity_evidence",
        ["document_id", "page"],
    )
    op.create_index(
        "ix_entity_evidence_workspace",
        "entity_evidence",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_entity_evidence_workspace", table_name="entity_evidence")
    op.drop_index("ix_entity_evidence_document_page", table_name="entity_evidence")
    op.drop_index("ix_entity_evidence_entity", table_name="entity_evidence")
    op.drop_table("entity_evidence")
