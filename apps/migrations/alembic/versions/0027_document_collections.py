"""Document collections as memory spaces + multi-format upload kinds.

Adds named document_collections (peer to agent/Slack memory spaces), stamps
documents.collection_id / entities.collection_id / relationships.collection_id,
and extends source_kind for text / markdown / email uploads.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_document_collections"
down_revision = "0026_ingestion_run_ontology"
branch_labels = None
depends_on = None

SOURCE_KINDS = (
    "pdf",
    "text",
    "markdown",
    "email",
    "north_conversation",
    "slack_conversation",
)

EPISODE_KINDS = (
    "pdf_chunk",
    "manual_text",
    "text_chunk",
    "markdown_chunk",
    "email_chunk",
    "north_message",
    "north_turn_window",
    "north_tool_event",
    "slack_message",
    "slack_turn_window",
)

UPLOAD_KINDS = ("pdf", "text", "markdown", "email")


def upgrade() -> None:
    op.create_table(
        "document_collections",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_document_collections_workspace",
        "document_collections",
        ["workspace_id"],
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_document_collections_workspace_name_ci
        ON document_collections (workspace_id, lower(name))
        """
    )

    op.add_column(
        "documents",
        sa.Column(
            "collection_id",
            sa.Uuid(),
            sa.ForeignKey("document_collections.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_documents_collection", "documents", ["collection_id"])
    op.create_check_constraint(
        "ck_documents_collection_upload_only",
        "documents",
        "collection_id IS NULL OR source_kind IN ("
        + ", ".join(repr(k) for k in UPLOAD_KINDS)
        + ")",
    )

    for table in ("entities", "relationships", "graphiti_entity_map", "graphiti_edge_map"):
        op.add_column(
            table,
            sa.Column(
                "collection_id",
                sa.Uuid(),
                sa.ForeignKey("document_collections.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index(f"ix_{table}_collection", table, ["collection_id"])

    # Replace global unique index: workspace-global rows have both agent and collection null.
    op.execute("DROP INDEX IF EXISTS uq_entities_workspace_global_type_name")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_entities_workspace_global_type_name
        ON entities (workspace_id, type, canonical_name)
        WHERE agent_id IS NULL AND collection_id IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_entities_workspace_collection_type_name
        ON entities (workspace_id, collection_id, type, canonical_name)
        WHERE collection_id IS NOT NULL AND agent_id IS NULL
        """
    )

    op.drop_constraint("ck_documents_source_mime", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_source_mime",
        "documents",
        "(source_kind = 'pdf' AND mime_type = 'application/pdf') OR "
        "(source_kind = 'text' AND mime_type = 'text/plain') OR "
        "(source_kind = 'markdown' AND mime_type IN ('text/markdown', 'text/plain')) OR "
        "(source_kind = 'email' AND mime_type = 'message/rfc822') OR "
        "(source_kind = 'north_conversation' AND mime_type = 'application/json') OR "
        "(source_kind = 'slack_conversation' AND mime_type = 'application/json')",
    )

    op.drop_constraint("ck_documents_source_kind", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_source_kind",
        "documents",
        "source_kind IN (" + ", ".join(repr(k) for k in SOURCE_KINDS) + ")",
    )

    op.drop_constraint("ck_episodes_kind", "episodes", type_="check")
    op.create_check_constraint(
        "ck_episodes_kind",
        "episodes",
        "kind IN (" + ", ".join(repr(k) for k in EPISODE_KINDS) + ")",
    )

    # GraphRAG indexes: collection memory space peer to agent_id.
    op.add_column(
        "graphrag_indexes",
        sa.Column(
            "collection_id",
            sa.Uuid(),
            sa.ForeignKey("document_collections.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_graphrag_indexes_ws_collection",
        "graphrag_indexes",
        ["workspace_id", "collection_id"],
    )
    op.create_check_constraint(
        "ck_graphrag_indexes_scope_xor",
        "graphrag_indexes",
        "NOT (agent_id IS NOT NULL AND collection_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_graphrag_indexes_scope_xor", "graphrag_indexes", type_="check")
    op.drop_index("ix_graphrag_indexes_ws_collection", table_name="graphrag_indexes")
    op.drop_column("graphrag_indexes", "collection_id")

    op.drop_constraint("ck_episodes_kind", "episodes", type_="check")
    op.create_check_constraint(
        "ck_episodes_kind",
        "episodes",
        "kind IN ("
        "'pdf_chunk', 'manual_text', 'north_message', 'north_turn_window', "
        "'north_tool_event', 'slack_message', 'slack_turn_window'"
        ")",
    )

    op.drop_constraint("ck_documents_source_kind", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_source_kind",
        "documents",
        "source_kind IN ('pdf', 'north_conversation', 'slack_conversation')",
    )

    op.drop_constraint("ck_documents_source_mime", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_source_mime",
        "documents",
        "(source_kind = 'pdf' AND mime_type = 'application/pdf') OR "
        "(source_kind = 'north_conversation' AND mime_type = 'application/json') OR "
        "(source_kind = 'slack_conversation' AND mime_type = 'application/json')",
    )

    op.execute("DROP INDEX IF EXISTS uq_entities_workspace_collection_type_name")
    op.execute("DROP INDEX IF EXISTS uq_entities_workspace_global_type_name")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_entities_workspace_global_type_name
        ON entities (workspace_id, type, canonical_name)
        WHERE agent_id IS NULL
        """
    )

    for table in ("graphiti_edge_map", "graphiti_entity_map", "relationships", "entities"):
        op.drop_index(f"ix_{table}_collection", table_name=table)
        op.drop_column(table, "collection_id")

    op.drop_constraint("ck_documents_collection_upload_only", "documents", type_="check")
    op.drop_index("ix_documents_collection", table_name="documents")
    op.drop_column("documents", "collection_id")

    op.execute("DROP INDEX IF EXISTS uq_document_collections_workspace_name_ci")
    op.drop_index("ix_document_collections_workspace", table_name="document_collections")
    op.drop_table("document_collections")
