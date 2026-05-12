"""Atomic notes, note links, entities, relationships, Graphiti ID maps."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005_notes_graph"
down_revision = "0004_documents_ingestion"
branch_labels = None
depends_on = None

NOTE_ORIGINS = ("generated", "manual", "merged", "split")
LINK_KINDS = ("related", "supports", "refutes", "extends", "references", "custom")
LINK_ORIGINS = ("generated", "manual")
REL_ORIGINS = ("generated", "manual")


def upgrade() -> None:
    op.create_table(
        "atomic_notes",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("is_user_edited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
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
        sa.CheckConstraint(f"origin IN ({', '.join(repr(o) for o in NOTE_ORIGINS)})", name="ck_atomic_notes_origin"),
    )
    op.create_index("ix_atomic_notes_workspace_updated", "atomic_notes", ["workspace_id", "updated_at"])
    op.execute(
        "CREATE INDEX ix_atomic_notes_tags ON atomic_notes USING gin (tags)",
    )
    op.execute(
        """
        CREATE INDEX ix_atomic_notes_fts ON atomic_notes
        USING gin (to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body, '')))
        """,
    )

    op.create_table(
        "note_episodes",
        sa.Column(
            "note_id",
            sa.Uuid(),
            sa.ForeignKey("atomic_notes.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "episode_id",
            sa.Uuid(),
            sa.ForeignKey("episodes.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )
    op.create_index("ix_note_episodes_episode", "note_episodes", ["episode_id"])

    op.create_table(
        "note_links",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_note_id",
            sa.Uuid(),
            sa.ForeignKey("atomic_notes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_note_id",
            sa.Uuid(),
            sa.ForeignKey("atomic_notes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("custom_label", sa.Text(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("source_note_id <> target_note_id", name="ck_note_links_no_self"),
        sa.CheckConstraint(f"kind IN ({', '.join(repr(k) for k in LINK_KINDS)})", name="ck_note_links_kind"),
        sa.CheckConstraint(f"origin IN ({', '.join(repr(o) for o in LINK_ORIGINS)})", name="ck_note_links_origin"),
        sa.CheckConstraint(
            "(kind <> 'custom') OR (custom_label IS NOT NULL AND length(trim(custom_label)) > 0)",
            name="ck_note_links_custom_label",
        ),
        sa.UniqueConstraint(
            "source_note_id",
            "target_note_id",
            "kind",
            "custom_label",
            name="uq_note_links_endpoints_kind",
        ),
    )
    op.create_index("ix_note_links_workspace", "note_links", ["workspace_id"])
    op.create_index("ix_note_links_source", "note_links", ["source_note_id"])
    op.create_index("ix_note_links_target", "note_links", ["target_note_id"])

    op.create_table(
        "entities",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("aliases", sa.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("properties", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_user_edited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
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
        sa.UniqueConstraint("workspace_id", "type", "canonical_name", name="uq_entities_workspace_type_name"),
    )
    op.create_index("ix_entities_workspace_type_name", "entities", ["workspace_id", "type", "canonical_name"])

    op.create_table(
        "entity_episodes",
        sa.Column(
            "entity_id",
            sa.Uuid(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "episode_id",
            sa.Uuid(),
            sa.ForeignKey("episodes.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )

    op.create_table(
        "entity_notes",
        sa.Column(
            "entity_id",
            sa.Uuid(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "note_id",
            sa.Uuid(),
            sa.ForeignKey("atomic_notes.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )

    op.create_table(
        "relationships",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_entity_id",
            sa.Uuid(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_entity_id",
            sa.Uuid(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("fact", sa.Text(), nullable=False, server_default=""),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Double(), nullable=False, server_default="1.0"),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("is_user_edited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
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
        sa.CheckConstraint(f"origin IN ({', '.join(repr(o) for o in REL_ORIGINS)})", name="ck_relationships_origin"),
    )
    op.create_index("ix_relationships_workspace_source", "relationships", ["workspace_id", "source_entity_id", "type"])
    op.create_index("ix_relationships_workspace_target", "relationships", ["workspace_id", "target_entity_id", "type"])

    op.create_table(
        "relationship_episodes",
        sa.Column(
            "relationship_id",
            sa.Uuid(),
            sa.ForeignKey("relationships.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "episode_id",
            sa.Uuid(),
            sa.ForeignKey("episodes.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )

    op.create_table(
        "relationship_notes",
        sa.Column(
            "relationship_id",
            sa.Uuid(),
            sa.ForeignKey("relationships.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "note_id",
            sa.Uuid(),
            sa.ForeignKey("atomic_notes.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )

    op.create_table(
        "graphiti_entity_map",
        sa.Column("graphiti_uuid", sa.Text(), primary_key=True, nullable=False),
        sa.Column(
            "entity_id",
            sa.Uuid(),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.create_index("ix_graphiti_entity_map_entity", "graphiti_entity_map", ["entity_id"])

    op.create_table(
        "graphiti_edge_map",
        sa.Column("graphiti_uuid", sa.Text(), primary_key=True, nullable=False),
        sa.Column(
            "relationship_id",
            sa.Uuid(),
            sa.ForeignKey("relationships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    op.create_index("ix_graphiti_edge_map_rel", "graphiti_edge_map", ["relationship_id"])


def downgrade() -> None:
    op.drop_table("graphiti_edge_map")
    op.drop_table("graphiti_entity_map")
    op.drop_table("relationship_notes")
    op.drop_table("relationship_episodes")
    op.drop_table("relationships")
    op.drop_table("entity_notes")
    op.drop_table("entity_episodes")
    op.drop_table("entities")
    op.drop_table("note_links")
    op.drop_table("note_episodes")
    op.execute("DROP INDEX IF EXISTS ix_atomic_notes_fts")
    op.execute("DROP INDEX IF EXISTS ix_atomic_notes_tags")
    op.drop_index("ix_atomic_notes_workspace_updated", table_name="atomic_notes")
    op.drop_table("atomic_notes")
