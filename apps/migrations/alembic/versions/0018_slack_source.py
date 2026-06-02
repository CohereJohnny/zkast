"""Slack source + generalized memory sources.

Adds Slack as a first-class ingestion source and generalizes the North-only
agent registry into a provider-neutral "memory source" concept (read-side
``memory_sources`` view over ``north_agents``; physical table/column rename is
intentionally deferred — see specs/openspecs/slack-source.md "Out of Scope").

Scope:
- ``documents.source_kind`` gains ``slack_conversation``; mime + agent checks extended.
- ``episodes.kind`` gains ``slack_message`` / ``slack_turn_window``.
- New ``slack_connections`` (per-workspace OAuth grant metadata; token itself lives
  encrypted in ``api_keys`` with kind ``slack_oauth``).
- New ``slack_conversation_cache`` (raw thread payloads, mirrors north cache).
- ``documents`` gains provider-neutral ``external_conversation_id`` + ``source_metadata``.
- ``north_agents`` gains ``provider_metadata`` (provider-specific descriptive fields).
- ``memory_sources`` view exposes the neutral registry shape.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# Keep revision id <= 32 chars (alembic_version.version_num is VARCHAR(32)).
revision = "0018_slack_source"
down_revision = "0017_dashboard_usage_agent_graph"
branch_labels = None
depends_on = None

SOURCE_KINDS = ("pdf", "north_conversation", "slack_conversation")

EPISODE_KINDS = (
    "pdf_chunk",
    "manual_text",
    "north_message",
    "north_turn_window",
    "north_tool_event",
    "slack_message",
    "slack_turn_window",
)


def upgrade() -> None:
    # ---- Generalize the agent registry (additive; no rename) --------------
    op.add_column(
        "north_agents",
        sa.Column(
            "provider_metadata",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # Provider-neutral read interface over the existing registry. Writers keep
    # using north_agents until a future sprint renames the physical table.
    op.execute(
        """
        CREATE VIEW memory_sources AS
        SELECT
            id,
            workspace_id,
            provider,
            external_agent_id AS external_id,
            display_name,
            import_settings,
            sync_cursor,
            provider_metadata,
            created_at,
            updated_at
        FROM north_agents
        """
    )

    # ---- documents: provider-neutral provenance + slack source kind -------
    op.add_column(
        "documents",
        sa.Column("external_conversation_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "source_metadata",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.drop_constraint("ck_documents_source_mime", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_source_mime",
        "documents",
        "(source_kind = 'pdf' AND mime_type = 'application/pdf') OR "
        "(source_kind = 'north_conversation' AND mime_type = 'application/json') OR "
        "(source_kind = 'slack_conversation' AND mime_type = 'application/json')",
    )

    op.drop_constraint("ck_documents_source_kind", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_source_kind",
        "documents",
        "source_kind IN (" + ", ".join(repr(k) for k in SOURCE_KINDS) + ")",
    )

    op.create_check_constraint(
        "ck_documents_slack_requires_agent",
        "documents",
        "source_kind <> 'slack_conversation' OR agent_id IS NOT NULL",
    )
    op.create_index(
        "ix_documents_external_conversation",
        "documents",
        ["workspace_id", "external_conversation_id"],
    )

    # ---- episodes: slack kinds -------------------------------------------
    op.drop_constraint("ck_episodes_kind", "episodes", type_="check")
    op.create_check_constraint(
        "ck_episodes_kind",
        "episodes",
        "kind IN (" + ", ".join(repr(k) for k in EPISODE_KINDS) + ")",
    )

    # ---- Slack OAuth credential: one per workspace ------------------------
    op.execute(
        """
        CREATE UNIQUE INDEX uq_api_keys_workspace_slack_oauth
        ON api_keys (workspace_id)
        WHERE kind = 'slack_oauth'
        """
    )

    # ---- slack_connections ------------------------------------------------
    op.create_table(
        "slack_connections",
        sa.Column("workspace_id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("slack_team_id", sa.Text(), nullable=False),
        sa.Column("slack_team_name", sa.Text(), nullable=True),
        sa.Column(
            "authed_scopes",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "installed_at",
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
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
    )

    # ---- slack_conversation_cache ----------------------------------------
    op.create_table(
        "slack_conversation_cache",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_conversation_id", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["north_agents.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "source_id",
            "external_conversation_id",
            name="uq_slack_cache_source_conversation",
        ),
    )
    op.create_index(
        "ix_slack_cache_workspace_source",
        "slack_conversation_cache",
        ["workspace_id", "source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_slack_cache_workspace_source", table_name="slack_conversation_cache")
    op.drop_table("slack_conversation_cache")
    op.drop_table("slack_connections")
    op.execute("DROP INDEX IF EXISTS uq_api_keys_workspace_slack_oauth")

    op.drop_constraint("ck_episodes_kind", "episodes", type_="check")
    op.create_check_constraint(
        "ck_episodes_kind",
        "episodes",
        "kind IN ("
        + ", ".join(
            repr(k)
            for k in (
                "pdf_chunk",
                "manual_text",
                "north_message",
                "north_turn_window",
                "north_tool_event",
            )
        )
        + ")",
    )

    op.drop_index("ix_documents_external_conversation", table_name="documents")
    op.drop_constraint("ck_documents_slack_requires_agent", "documents", type_="check")
    op.drop_constraint("ck_documents_source_kind", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_source_kind",
        "documents",
        "source_kind IN ('pdf', 'north_conversation')",
    )
    op.drop_constraint("ck_documents_source_mime", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_source_mime",
        "documents",
        "(source_kind = 'pdf' AND mime_type = 'application/pdf') OR "
        "(source_kind = 'north_conversation' AND mime_type = 'application/json')",
    )
    op.drop_column("documents", "source_metadata")
    op.drop_column("documents", "external_conversation_id")

    op.execute("DROP VIEW IF EXISTS memory_sources")
    op.drop_column("north_agents", "provider_metadata")
