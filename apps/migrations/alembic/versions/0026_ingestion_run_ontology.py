"""Add ontology_name / ontology_version to ingestion_runs for document-level selection."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_ingestion_run_ontology"
down_revision = "0025_harness_presets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingestion_runs",
        sa.Column("ontology_name", sa.Text(), nullable=False, server_default="generic"),
    )
    op.add_column(
        "ingestion_runs",
        sa.Column("ontology_version", sa.Text(), nullable=False, server_default="v1"),
    )


def downgrade() -> None:
    op.drop_column("ingestion_runs", "ontology_version")
    op.drop_column("ingestion_runs", "ontology_name")
