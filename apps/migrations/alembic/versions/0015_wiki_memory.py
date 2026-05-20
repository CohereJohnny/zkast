"""LLM Wiki memory: spaces, pages, sources, jobs, mutations, links."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0015_wiki_memory"
down_revision = "0014_chat_retrieval_modes"
branch_labels = None
depends_on = None


WIKI_SCOPE_KINDS = ("workspace", "agent", "document", "conversation")
WIKI_SPACE_STATUSES = ("empty", "generating", "ready", "stale", "failed")
WIKI_PAGE_TYPES = (
    "source_summary",
    "entity",
    "topic",
    "synthesis",
    "comparison",
    "index",
    "changelog",
)
WIKI_PAGE_STATUSES = ("draft", "ready", "stale", "archived", "failed")
WIKI_JOB_KINDS = ("generate", "refresh", "lint", "regenerate_page")
WIKI_JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
WIKI_LINK_KINDS = ("related", "contains", "contradicts", "supports", "supersedes", "references")
WIKI_MUTATION_TYPES = (
    "page_created",
    "page_updated",
    "page_renamed",
    "page_archived",
    "link_added",
    "link_removed",
    "citation_added",
    "contradiction_flagged",
    "page_marked_stale",
)


def _check_in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(repr(v) for v in values) + ")"


def upgrade() -> None:
    op.create_table(
        "wiki_spaces",
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
            nullable=True,
        ),
        sa.Column("scope_kind", sa.Text(), nullable=False, server_default="workspace"),
        sa.Column("scope_target_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="empty"),
        sa.Column(
            "settings",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_generated_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_check_constraint(
        "ck_wiki_spaces_scope_kind",
        "wiki_spaces",
        f"scope_kind IN {_check_in(WIKI_SCOPE_KINDS)}",
    )
    op.create_check_constraint(
        "ck_wiki_spaces_status",
        "wiki_spaces",
        f"status IN {_check_in(WIKI_SPACE_STATUSES)}",
    )
    op.create_check_constraint(
        "ck_wiki_spaces_agent_scope",
        "wiki_spaces",
        "(scope_kind = 'agent' AND agent_id IS NOT NULL) OR (scope_kind <> 'agent')",
    )
    op.create_index("ix_wiki_spaces_workspace", "wiki_spaces", ["workspace_id"])
    op.create_index("ix_wiki_spaces_agent", "wiki_spaces", ["agent_id"])
    op.create_unique_constraint(
        "uq_wiki_spaces_scope_per_workspace",
        "wiki_spaces",
        ["workspace_id", "scope_kind", "scope_target_id"],
    )

    op.create_table(
        "wiki_pages",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "wiki_space_id",
            sa.Uuid(),
            sa.ForeignKey("wiki_spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("page_type", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("confidence", sa.Float(), nullable=True),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("wiki_space_id", "slug", name="uq_wiki_pages_space_slug"),
    )
    op.create_check_constraint(
        "ck_wiki_pages_type",
        "wiki_pages",
        f"page_type IN {_check_in(WIKI_PAGE_TYPES)}",
    )
    op.create_check_constraint(
        "ck_wiki_pages_status",
        "wiki_pages",
        f"status IN {_check_in(WIKI_PAGE_STATUSES)}",
    )
    op.create_index("ix_wiki_pages_space_type", "wiki_pages", ["wiki_space_id", "page_type"])
    op.create_index("ix_wiki_pages_space_status", "wiki_pages", ["wiki_space_id", "status"])

    op.create_table(
        "wiki_page_sources",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "wiki_page_id",
            sa.Uuid(),
            sa.ForeignKey("wiki_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_wiki_page_sources_page", "wiki_page_sources", ["wiki_page_id"])
    op.create_index(
        "ix_wiki_page_sources_lookup",
        "wiki_page_sources",
        ["source_kind", "source_id"],
    )

    op.create_table(
        "wiki_generation_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "wiki_space_id",
            sa.Uuid(),
            sa.ForeignKey("wiki_spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False, server_default="generate"),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
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
    op.create_check_constraint(
        "ck_wiki_jobs_kind",
        "wiki_generation_jobs",
        f"kind IN {_check_in(WIKI_JOB_KINDS)}",
    )
    op.create_check_constraint(
        "ck_wiki_jobs_status",
        "wiki_generation_jobs",
        f"status IN {_check_in(WIKI_JOB_STATUSES)}",
    )
    op.create_index(
        "ix_wiki_jobs_workspace",
        "wiki_generation_jobs",
        ["workspace_id", "started_at"],
    )
    op.create_index(
        "ix_wiki_jobs_space",
        "wiki_generation_jobs",
        ["wiki_space_id", "started_at"],
    )

    op.create_table(
        "wiki_mutations",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "wiki_job_id",
            sa.Uuid(),
            sa.ForeignKey("wiki_generation_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "wiki_page_id",
            sa.Uuid(),
            sa.ForeignKey("wiki_pages.id", ondelete="CASCADE"),
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
    op.create_check_constraint(
        "ck_wiki_mutations_type",
        "wiki_mutations",
        f"mutation_type IN {_check_in(WIKI_MUTATION_TYPES)}",
    )
    op.create_index("ix_wiki_mutations_job", "wiki_mutations", ["wiki_job_id"])

    op.create_table(
        "wiki_links",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "source_page_id",
            sa.Uuid(),
            sa.ForeignKey("wiki_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_page_id",
            sa.Uuid(),
            sa.ForeignKey("wiki_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False, server_default="related"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("strength", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "source_page_id",
            "target_page_id",
            "kind",
            name="uq_wiki_links_source_target_kind",
        ),
    )
    op.create_check_constraint(
        "ck_wiki_links_kind",
        "wiki_links",
        f"kind IN {_check_in(WIKI_LINK_KINDS)}",
    )
    op.create_check_constraint(
        "ck_wiki_links_self",
        "wiki_links",
        "source_page_id <> target_page_id",
    )


def downgrade() -> None:
    op.drop_table("wiki_links")
    op.drop_index("ix_wiki_mutations_job", table_name="wiki_mutations")
    op.drop_table("wiki_mutations")
    op.drop_index("ix_wiki_jobs_space", table_name="wiki_generation_jobs")
    op.drop_index("ix_wiki_jobs_workspace", table_name="wiki_generation_jobs")
    op.drop_table("wiki_generation_jobs")
    op.drop_index("ix_wiki_page_sources_lookup", table_name="wiki_page_sources")
    op.drop_index("ix_wiki_page_sources_page", table_name="wiki_page_sources")
    op.drop_table("wiki_page_sources")
    op.drop_index("ix_wiki_pages_space_status", table_name="wiki_pages")
    op.drop_index("ix_wiki_pages_space_type", table_name="wiki_pages")
    op.drop_table("wiki_pages")
    op.drop_index("ix_wiki_spaces_agent", table_name="wiki_spaces")
    op.drop_index("ix_wiki_spaces_workspace", table_name="wiki_spaces")
    op.drop_table("wiki_spaces")
