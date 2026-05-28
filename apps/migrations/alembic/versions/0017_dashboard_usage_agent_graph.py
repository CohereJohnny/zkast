"""Dashboard usage events and agent-scoped graph isolation."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0017_dashboard_usage_agent_graph"
down_revision = "0016_eval_memory_extensions"
branch_labels = None
depends_on = None

USAGE_SOURCES = ("chat", "ingestion", "wiki", "dream", "eval", "retrieval", "other")


def _check_in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(repr(v) for v in values) + ")"


def upgrade() -> None:
    # ---- Agent-scoped graph rows ------------------------------------------
    op.add_column(
        "entities",
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("north_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "relationships",
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("north_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "graphiti_entity_map",
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("north_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "graphiti_edge_map",
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("north_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.drop_constraint("uq_entities_workspace_type_name", "entities", type_="unique")
    op.create_index("ix_entities_agent", "entities", ["agent_id"])
    op.create_index("ix_relationships_agent", "relationships", ["agent_id"])
    op.create_index("ix_graphiti_entity_map_agent", "graphiti_entity_map", ["agent_id"])
    op.create_index("ix_graphiti_edge_map_agent", "graphiti_edge_map", ["agent_id"])

    op.execute(
        """
        CREATE UNIQUE INDEX uq_entities_workspace_global_type_name
        ON entities (workspace_id, type, canonical_name)
        WHERE agent_id IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_entities_workspace_agent_type_name
        ON entities (workspace_id, agent_id, type, canonical_name)
        WHERE agent_id IS NOT NULL
        """
    )

    # Backfill agent_id from linked episodes/documents where possible.
    op.execute(
        """
        UPDATE entities e
        SET agent_id = sub.agent_id
        FROM (
          SELECT DISTINCT ON (ee.entity_id) ee.entity_id, ep.agent_id
          FROM entity_episodes ee
          JOIN episodes ep ON ep.id = ee.episode_id
          WHERE ep.agent_id IS NOT NULL
          ORDER BY ee.entity_id, ep.created_at DESC
        ) sub
        WHERE e.id = sub.entity_id AND e.agent_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE graphiti_entity_map m
        SET agent_id = e.agent_id
        FROM entities e
        WHERE e.id = m.entity_id AND m.agent_id IS NULL
        """
    )

    # ---- Durable usage / token accounting ---------------------------------
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("north_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("north_conversation_id", sa.Text(), nullable=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("job_id", sa.Text(), nullable=True),
        sa.Column(
            "ingestion_run_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("usage_source", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metadata",
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
    )
    op.create_check_constraint(
        "ck_usage_events_source",
        "usage_events",
        f"usage_source IN {_check_in(USAGE_SOURCES)}",
    )
    op.create_index("ix_usage_events_workspace", "usage_events", ["workspace_id", "created_at"])
    op.create_index("ix_usage_events_agent", "usage_events", ["workspace_id", "agent_id"])
    op.create_index("ix_usage_events_source", "usage_events", ["workspace_id", "usage_source"])

    # Backfill chat token usage from persisted messages.
    op.execute(
        """
        INSERT INTO usage_events (
          id, workspace_id, agent_id, usage_source, stage, tokens_in, tokens_out, metadata, created_at
        )
        SELECT
          gen_random_uuid(),
          cs.workspace_id,
          NULLIF(cs.scope->>'agent_id', '')::uuid,
          'chat',
          'chat_turn',
          COALESCE(cm.tokens_in, 0),
          COALESCE(cm.tokens_out, 0),
          jsonb_build_object('message_id', cm.id::text, 'session_id', cs.id::text),
          cm.created_at
        FROM chat_messages cm
        JOIN chat_sessions cs ON cs.id = cm.session_id
        WHERE cs.workspace_id IS NOT NULL
          AND (COALESCE(cm.tokens_in, 0) + COALESCE(cm.tokens_out, 0)) > 0
        """
    )

    # Backfill eval token usage.
    op.execute(
        """
        INSERT INTO usage_events (
          id, workspace_id, usage_source, stage, tokens_in, tokens_out, metadata, created_at
        )
        SELECT
          gen_random_uuid(),
          r.workspace_id,
          'eval',
          COALESCE(r.eval_kind, 'eval'),
          COALESCE(res.tokens_in, 0),
          COALESCE(res.tokens_out, 0),
          jsonb_build_object('run_id', r.id::text, 'result_id', res.id::text),
          res.created_at
        FROM chat_eval_results res
        JOIN chat_eval_runs r ON r.id = res.run_id
        WHERE (COALESCE(res.tokens_in, 0) + COALESCE(res.tokens_out, 0)) > 0
        """
    )


def downgrade() -> None:
    op.drop_table("usage_events")

    op.drop_index("uq_entities_workspace_agent_type_name", table_name="entities")
    op.drop_index("uq_entities_workspace_global_type_name", table_name="entities")
    op.drop_index("ix_graphiti_edge_map_agent", table_name="graphiti_edge_map")
    op.drop_index("ix_graphiti_entity_map_agent", table_name="graphiti_entity_map")
    op.drop_index("ix_relationships_agent", table_name="relationships")
    op.drop_index("ix_entities_agent", table_name="entities")

    op.drop_column("graphiti_edge_map", "agent_id")
    op.drop_column("graphiti_entity_map", "agent_id")
    op.drop_column("relationships", "agent_id")
    op.drop_column("entities", "agent_id")

    op.create_unique_constraint(
        "uq_entities_workspace_type_name",
        "entities",
        ["workspace_id", "type", "canonical_name"],
    )
