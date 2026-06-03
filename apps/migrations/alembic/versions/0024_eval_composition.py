"""Record the full pipeline-stage composition on each eval result.

Adds chat_eval_results.composition (JSONB): {extractor, ontology_version,
graph_store, retrieval_strategy, provider, content_hash}. Enables comparing
configurations and attributing metric deltas to a specific stage (hold-all-
vary-one), per specs/openspecs/composable-eval-harness.md.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0024_eval_composition"
down_revision = "0023_graphrag_community_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chat_eval_results",
        sa.Column("composition", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("chat_eval_results", "composition")
