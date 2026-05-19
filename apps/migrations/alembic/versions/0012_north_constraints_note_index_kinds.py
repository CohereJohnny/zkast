"""North document agent constraint, north_bearer api_keys uniqueness, note index kinds."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Keep revision id <= 32 chars: ``alembic_version.version_num`` is VARCHAR(32) in this project.
revision = "0012_north_constraints"
down_revision = "0011_north_agents_amem"
branch_labels = None
depends_on = None

# Must match 0010 + new kinds (see retrieval_embeddings_repo.VALID_INDEX_KINDS).
INDEX_KINDS = (
    "raw_chunk",
    "atomic_note",
    "entity",
    "relationship",
    "graph_context",
    "note_zettel",
    "note_amem",
)


def upgrade() -> None:
    op.create_check_constraint(
        "ck_documents_north_requires_agent",
        "documents",
        "source_kind <> 'north_conversation' OR agent_id IS NOT NULL",
    )

    op.execute(
        """
        CREATE UNIQUE INDEX uq_api_keys_workspace_north_bearer
        ON api_keys (workspace_id)
        WHERE kind = 'north_bearer'
        """
    )

    op.drop_constraint(
        "ck_retrieval_embeddings_index_kind",
        "retrieval_embeddings",
        type_="check",
    )
    op.create_check_constraint(
        "ck_retrieval_embeddings_index_kind",
        "retrieval_embeddings",
        "index_kind IN ("
        + ", ".join(repr(k) for k in INDEX_KINDS)
        + ")",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_retrieval_embeddings_index_kind",
        "retrieval_embeddings",
        type_="check",
    )
    op.create_check_constraint(
        "ck_retrieval_embeddings_index_kind",
        "retrieval_embeddings",
        "index_kind IN ('raw_chunk', 'atomic_note', 'entity', 'relationship', 'graph_context')",
    )

    op.execute("DROP INDEX IF EXISTS uq_api_keys_workspace_north_bearer")
    op.drop_constraint("ck_documents_north_requires_agent", "documents", type_="check")
