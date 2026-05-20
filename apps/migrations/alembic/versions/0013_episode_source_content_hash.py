"""Per-episode source content hash for skip-reprocess dedup."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_episode_content_hash"
down_revision = "0012_north_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("episodes", sa.Column("source_content_hash", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE episodes
        SET source_content_hash = encode(sha256(convert_to(text, 'UTF8')), 'hex')
        WHERE source_content_hash IS NULL AND text IS NOT NULL
        """,
    )
    op.create_index(
        "ix_episodes_document_source_hash",
        "episodes",
        ["document_id", "source_content_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_episodes_document_source_hash", table_name="episodes")
    op.drop_column("episodes", "source_content_hash")
