"""Initial users, workspaces, memberships + bypass seed."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None

# Fixed IDs for P0 bypass user + default workspace (override in app via env for reads only).
BYPASS_USER_ID = "00000000-0000-4000-8000-000000000001"
DEFAULT_WORKSPACE_ID = "00000000-0000-4000-8000-000000000002"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("auth_provider", sa.Text(), nullable=False),
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
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "pipeline_settings",
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
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)

    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
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
        sa.UniqueConstraint("user_id", "workspace_id", name="uq_memberships_user_workspace"),
    )
    op.create_index("ix_memberships_workspace_id", "memberships", ["workspace_id"])

    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            INSERT INTO users (id, email, display_name, auth_provider)
            VALUES (:id, NULL, 'Local user', 'bypass')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": BYPASS_USER_ID},
    )

    conn.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, slug, description, pipeline_settings)
            VALUES (:id, 'Default workspace', 'default', NULL, '{}'::jsonb)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": DEFAULT_WORKSPACE_ID},
    )

    # Membership linking bypass user to default workspace (idempotent via gen_random_uuid per row — use NOT EXISTS)
    conn.execute(
        sa.text(
            """
            INSERT INTO memberships (id, user_id, workspace_id, role)
            SELECT gen_random_uuid(), CAST(:uid AS uuid), CAST(:wid AS uuid), 'owner'
            WHERE NOT EXISTS (
              SELECT 1 FROM memberships m
              WHERE m.user_id = CAST(:uid AS uuid) AND m.workspace_id = CAST(:wid AS uuid)
            )
            """
        ),
        {"uid": BYPASS_USER_ID, "wid": DEFAULT_WORKSPACE_ID},
    )


def downgrade() -> None:
    op.drop_index("ix_memberships_workspace_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_index("ix_workspaces_slug", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
