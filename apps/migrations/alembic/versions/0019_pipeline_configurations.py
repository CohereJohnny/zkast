"""Pipeline configurations registry (composable evaluation harness).

A Pipeline Configuration is a named, versioned, content-hashed composition of
stage choices (extractor x ontology/prompt-set x graph store x retrieval
strategy x provider). The DB table is the runtime store of record; the portable
YAML representation lives in the repo and seeds this table. This migration also
seeds the global ``builtin-default`` configuration representing today's
production pipeline (Graphiti extraction + Graphiti/FalkorDB store + graph
retrieval).

See specs/openspecs/composable-eval-harness.md.
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0019_pipeline_configurations"
down_revision = "0018_slack_source"
branch_labels = None
depends_on = None


def _content_hash(normalized: dict) -> str:
    blob = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def upgrade() -> None:
    op.create_table(
        "pipeline_configurations",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        # NULL workspace_id = global/built-in configuration available to all workspaces.
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("extractor", sa.Text(), nullable=False),
        sa.Column("ontology_version", sa.Text(), nullable=True),
        sa.Column("graph_store", sa.Text(), nullable=False),
        sa.Column("retrieval_strategy", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False, server_default="cohere_compat"),
        sa.Column("params", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
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
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "uq_pipeline_configurations_name_version",
        "pipeline_configurations",
        ["workspace_id", "name", "version"],
        unique=True,
    )

    # Seed the global built-in default = current production pipeline.
    normalized = {
        "extractor": "graphiti",
        "graph_store": "graphiti_falkor",
        "retrieval_strategy": "graph",
        "ontology_version": "generic_v1",
        "provider": "cohere_compat",
        "params": {},
    }
    op.execute(
        sa.text(
            """
            INSERT INTO pipeline_configurations (
              id, workspace_id, name, description, extractor, ontology_version,
              graph_store, retrieval_strategy, provider, params, version,
              content_hash, is_builtin
            )
            VALUES (
              gen_random_uuid(), NULL, :name, :description, :extractor, :ontology_version,
              :graph_store, :retrieval_strategy, :provider, '{}'::jsonb, 1,
              :content_hash, true
            )
            """
        ).bindparams(
            name="builtin-default",
            description=(
                "Current production pipeline: Graphiti typed extraction "
                "(generic ontology) + Graphiti/FalkorDB store + graph retrieval."
            ),
            extractor="graphiti",
            ontology_version="generic_v1",
            graph_store="graphiti_falkor",
            retrieval_strategy="graph",
            provider="cohere_compat",
            content_hash=_content_hash(normalized),
        )
    )


def downgrade() -> None:
    op.drop_index(
        "uq_pipeline_configurations_name_version",
        table_name="pipeline_configurations",
    )
    op.drop_table("pipeline_configurations")
