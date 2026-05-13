"""Sprint 6: chat_sessions, chat_messages, retrieval_records, chat_citations.

Schema for grounded chat per the Chat section of
[specs/datamodel.md](../../specs/datamodel.md).

Key design points:
- ``chat_sessions.scope`` and ``model_settings`` are JSONB — the scope
  dimensions (``document_ids``, ``tags``, ``entity_types``, ``edge_types``,
  ``valid_at``, ``seed_entity_ids``) compose freely and can extend
  per-workspace without re-migrating.
- ``chat_messages`` carries Sprint 7 regeneration fields up front
  (``parent_message_id``, ``is_active_alternate``) so we don't have to add
  them later. A partial unique index enforces "exactly one active assistant
  per (session, sequence)" — alternates share ``sequence`` but only one is
  active at a time.
- ``chat_messages.retrieval_mode`` defaults to ``'graph'`` so Sprint 6b's
  GraphRAG-vs-RAG eval can read the column without a follow-up migration.
- ``retrieval_records.message_id`` is UNIQUE (one record per assistant
  message) and CASCADE-deletes with the message.
- ``chat_citations.sources`` is JSONB of structured source descriptors
  (kind, id, document_id, page_start, page_end, excerpt) — see
  ``apps/pipeline/app/chat_repo.py``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009_chat_tables"
down_revision = "0008_entity_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # chat_sessions ---------------------------------------------------------
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "scope",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "share_visibility",
            sa.Text(),
            nullable=False,
            server_default="private",
        ),
        sa.Column(
            "model_settings",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "pinned_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("graph_snapshots.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "share_visibility IN ('private','workspace_read','workspace_edit')",
            name="ck_chat_sessions_share_visibility",
        ),
    )
    op.create_index(
        "ix_chat_sessions_workspace_last_activity",
        "chat_sessions",
        ["workspace_id", sa.text("last_activity_at DESC")],
    )
    op.create_index(
        "ix_chat_sessions_workspace_creator_activity",
        "chat_sessions",
        ["workspace_id", "created_by_user_id", sa.text("last_activity_at DESC")],
    )

    # chat_messages ---------------------------------------------------------
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "parent_message_id",
            sa.Uuid(),
            sa.ForeignKey("chat_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_active_alternate",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "author_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("effective_scope_snapshot", JSONB(), nullable=True),
        sa.Column("model_used", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        # Sprint 6b — `graph` (default) or `rag`. Stored on every turn so the
        # eval harness can join messages by mode without a re-migration.
        sa.Column(
            "retrieval_mode",
            sa.Text(),
            nullable=False,
            server_default="graph",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "role IN ('user','assistant','system','tool')",
            name="ck_chat_messages_role",
        ),
        sa.CheckConstraint(
            "status IN ('pending','streaming','complete','cancelled','failed','refused')",
            name="ck_chat_messages_status",
        ),
        sa.CheckConstraint(
            "retrieval_mode IN ('graph','rag','hybrid')",
            name="ck_chat_messages_retrieval_mode",
        ),
    )
    op.create_index(
        "ix_chat_messages_session_sequence",
        "chat_messages",
        ["session_id", "sequence"],
    )
    op.create_index(
        "ix_chat_messages_session_created",
        "chat_messages",
        ["session_id", "created_at"],
    )
    # Partial unique index — alternates share sequence but only one row may
    # carry `is_active_alternate = true` per (session, sequence). Enforces
    # the single-active-assistant invariant from datamodel.md.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_chat_messages_session_sequence_active
        ON chat_messages (session_id, sequence)
        WHERE is_active_alternate = true
        """
    )

    # retrieval_records -----------------------------------------------------
    op.create_table(
        "retrieval_records",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "retrieval_strategy",
            sa.Text(),
            nullable=False,
            server_default="graphiti_hybrid_v1",
        ),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column(
            "retrieved_items",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("total_candidates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "truncated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_retrieval_records_workspace_created",
        "retrieval_records",
        ["workspace_id", sa.text("created_at DESC")],
    )

    # chat_citations --------------------------------------------------------
    op.create_table(
        "chat_citations",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("chat_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text_start", sa.Integer(), nullable=False),
        sa.Column("text_end", sa.Integer(), nullable=False),
        sa.Column(
            "sources",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("text_start < text_end", name="ck_chat_citations_range"),
    )
    op.create_index(
        "ix_chat_citations_message",
        "chat_citations",
        ["message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_citations_message", table_name="chat_citations")
    op.drop_table("chat_citations")
    op.drop_index(
        "ix_retrieval_records_workspace_created",
        table_name="retrieval_records",
    )
    op.drop_table("retrieval_records")
    op.execute("DROP INDEX IF EXISTS uq_chat_messages_session_sequence_active")
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_session_sequence", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index(
        "ix_chat_sessions_workspace_creator_activity",
        table_name="chat_sessions",
    )
    op.drop_index(
        "ix_chat_sessions_workspace_last_activity",
        table_name="chat_sessions",
    )
    op.drop_table("chat_sessions")
