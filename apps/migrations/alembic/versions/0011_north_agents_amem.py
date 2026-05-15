"""North agents, transcript documents, episode kinds, A-MEM note fields, dreaming."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011_north_agents_amem"
down_revision = "0010_retrieval_eval_indexes"
branch_labels = None
depends_on = None

EPISODE_KINDS = (
    "pdf_chunk",
    "manual_text",
    "north_message",
    "north_turn_window",
    "north_tool_event",
)

DOC_SOURCE_KINDS = ("pdf", "north_conversation")


def upgrade() -> None:
    op.create_table(
        "north_agents",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_agent_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False, server_default="north"),
        sa.Column("display_name", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "import_settings",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("sync_cursor", sa.Text(), nullable=True),
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
        sa.UniqueConstraint(
            "workspace_id",
            "provider",
            "external_agent_id",
            name="uq_north_agents_workspace_provider_external",
        ),
    )
    op.create_index("ix_north_agents_workspace", "north_agents", ["workspace_id"])

    op.create_table(
        "north_conversation_cache",
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
            sa.ForeignKey("north_agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("north_conversation_id", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "agent_id",
            "north_conversation_id",
            name="uq_north_conv_cache_agent_conv",
        ),
    )
    op.create_index("ix_north_conv_cache_workspace", "north_conversation_cache", ["workspace_id"])

    op.add_column(
        "documents",
        sa.Column(
            "source_kind",
            sa.Text(),
            nullable=False,
            server_default="pdf",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("north_agents.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column("documents", sa.Column("north_conversation_id", sa.Text(), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "north_metadata",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("documents", sa.Column("raw_transcript_json", JSONB(), nullable=True))

    op.drop_constraint("ck_documents_mime_pdf", "documents", type_="check")
    op.create_check_constraint(
        "ck_documents_source_mime",
        "documents",
        "(source_kind = 'pdf' AND mime_type = 'application/pdf') OR "
        "(source_kind = 'north_conversation' AND mime_type = 'application/json')",
    )
    op.create_check_constraint(
        "ck_documents_source_kind",
        "documents",
        "source_kind IN ('pdf', 'north_conversation')",
    )
    op.create_index("ix_documents_agent", "documents", ["agent_id"])
    op.create_index("ix_documents_workspace_source", "documents", ["workspace_id", "source_kind"])

    op.drop_constraint("ck_episodes_kind", "episodes", type_="check")
    op.add_column(
        "episodes",
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("north_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_episodes_kind",
        "episodes",
        "kind IN ("
        + ", ".join(repr(k) for k in EPISODE_KINDS)
        + ")",
    )
    op.create_index("ix_episodes_agent", "episodes", ["agent_id"])

    op.add_column(
        "atomic_notes",
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("north_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("atomic_notes", sa.Column("memory_context", sa.Text(), nullable=True))
    op.add_column(
        "atomic_notes",
        sa.Column(
            "memory_keywords",
            sa.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.add_column(
        "atomic_notes",
        sa.Column(
            "evolution_history",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("atomic_notes", sa.Column("dreaming_touched_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_atomic_notes_agent", "atomic_notes", ["agent_id"])

    op.add_column("note_links", sa.Column("link_reason", sa.Text(), nullable=True))
    op.add_column(
        "note_links",
        sa.Column(
            "link_strength",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
    )

    op.add_column(
        "retrieval_embeddings",
        sa.Column(
            "agent_id",
            sa.Uuid(),
            sa.ForeignKey("north_agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_retrieval_embeddings_agent", "retrieval_embeddings", ["agent_id"])

    op.create_table(
        "dream_jobs",
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
            sa.ForeignKey("north_agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "stats",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_dream_jobs_workspace", "dream_jobs", ["workspace_id", "started_at"])

    op.create_table(
        "dream_job_mutations",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "dream_job_id",
            sa.Uuid(),
            sa.ForeignKey("dream_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "note_id",
            sa.Uuid(),
            sa.ForeignKey("atomic_notes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mutation_type", sa.Text(), nullable=False),
        sa.Column(
            "payload",
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
    op.create_index("ix_dream_mutations_job", "dream_job_mutations", ["dream_job_id"])


def downgrade() -> None:
    op.drop_index("ix_dream_mutations_job", table_name="dream_job_mutations")
    op.drop_table("dream_job_mutations")
    op.drop_index("ix_dream_jobs_workspace", table_name="dream_jobs")
    op.drop_table("dream_jobs")

    op.drop_index("ix_retrieval_embeddings_agent", table_name="retrieval_embeddings")
    op.drop_column("retrieval_embeddings", "agent_id")

    op.drop_column("note_links", "link_strength")
    op.drop_column("note_links", "link_reason")

    op.drop_index("ix_atomic_notes_agent", table_name="atomic_notes")
    op.drop_column("atomic_notes", "dreaming_touched_at")
    op.drop_column("atomic_notes", "evolution_history")
    op.drop_column("atomic_notes", "memory_keywords")
    op.drop_column("atomic_notes", "memory_context")
    op.drop_column("atomic_notes", "agent_id")

    op.drop_index("ix_episodes_agent", table_name="episodes")
    op.drop_column("episodes", "agent_id")
    op.drop_constraint("ck_episodes_kind", "episodes", type_="check")
    op.create_check_constraint(
        "ck_episodes_kind",
        "episodes",
        "kind IN ('pdf_chunk', 'manual_text')",
    )

    op.execute("DELETE FROM documents WHERE source_kind = 'north_conversation'")

    op.drop_index("ix_documents_workspace_source", table_name="documents")
    op.drop_index("ix_documents_agent", table_name="documents")
    op.drop_constraint("ck_documents_source_kind", "documents", type_="check")
    op.drop_constraint("ck_documents_source_mime", "documents", type_="check")
    op.drop_column("documents", "raw_transcript_json")
    op.drop_column("documents", "north_metadata")
    op.drop_column("documents", "north_conversation_id")
    op.drop_column("documents", "agent_id")
    op.drop_column("documents", "source_kind")
    op.create_check_constraint(
        "ck_documents_mime_pdf",
        "documents",
        "mime_type = 'application/pdf'",
    )

    op.drop_index("ix_north_conv_cache_workspace", table_name="north_conversation_cache")
    op.drop_table("north_conversation_cache")

    op.drop_index("ix_north_agents_workspace", table_name="north_agents")
    op.drop_table("north_agents")
