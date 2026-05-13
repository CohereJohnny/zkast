"""Sprint 6b: retrieval embeddings index + chat eval tables.

Two concerns rolled into one migration:

1. ``retrieval_embeddings`` — a shared physical embeddings store with a
   strict ``index_kind`` discriminator. The Sprint 6b evaluation depends
   on a hard separation between the Naive-RAG baseline (raw parsed
   document chunks only) and the GraphRAG modes (zettelkasten /
   entity / relationship / graph-context artifacts). Queries filter by
   ``index_kind`` to enforce that boundary; tests pin it.

2. ``chat_eval_runs`` / ``chat_eval_questions`` / ``chat_eval_results``
   — persist eval runs so we can compare retrieval modes side by side
   in the Chat UI and reproduce a previous measurement at any time.

Notes:
- Uses the pgvector ``vector`` type. Dimension defaults to 1536 to
  match Cohere ``embed-v4.0`` at our deployment width
  (``EMBEDDING_DIM=1536``). Cohere also returns 256/512/1024 widths;
  if/when we switch defaults we'll need a new column or a re-embed.
- An IVFFLAT index is the safe choice for cold-start workloads
  (HNSW requires ``CREATE INDEX ... USING hnsw`` extension support
  that lands in pgvector 0.5+ — IVFFLAT works on every supported
  pgvector release and is plenty for the workspace-scoped sizes we
  see in P0).
- ``source_id`` is ``TEXT`` rather than ``UUID`` because some
  index kinds (``graph_context``, future ``synthetic`` rows) are
  identified by a stable string key, not a Postgres row id.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010_retrieval_eval_indexes"
down_revision = "0009_chat_tables"
branch_labels = None
depends_on = None


# Allowed values for ``retrieval_embeddings.index_kind``. The migration
# pins these via a CHECK constraint; Phase 2 of Sprint 6b enforces the
# Naive-RAG boundary by always passing ``index_kind = 'raw_chunk'`` and
# never reading rows of other kinds.
INDEX_KINDS = (
    "raw_chunk",
    "atomic_note",
    "entity",
    "relationship",
    "graph_context",
)


def upgrade() -> None:
    # Enable the pgvector extension. The image is now ``pgvector/pgvector:pg16``
    # (see docker-compose.yml) so the extension is available.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---- retrieval_embeddings ---------------------------------------------
    op.create_table(
        "retrieval_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("index_kind", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("chunk_sequence", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "embedding_model", sa.Text(), nullable=False, server_default="embed-v4.0"
        ),
        sa.Column("embedding_dim", sa.Integer(), nullable=False, server_default="1536"),
        sa.Column(
            "attributes",
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
        sa.CheckConstraint(
            "index_kind IN ("
            + ", ".join(f"'{k}'" for k in INDEX_KINDS)
            + ")",
            name="ck_retrieval_embeddings_index_kind",
        ),
    )

    # Add the pgvector column via raw SQL — Alembic / SQLAlchemy core have
    # no ``vector`` type. Matches our Cohere embed-v4.0 deployment width
    # (1536). Stored as the native pgvector ``vector`` type so cosine
    # distance (``<=>``) works.
    op.execute(
        "ALTER TABLE retrieval_embeddings "
        "ADD COLUMN embedding vector(1536) NOT NULL"
    )

    op.create_index(
        "ix_retrieval_embeddings_workspace_kind",
        "retrieval_embeddings",
        ["workspace_id", "index_kind"],
    )
    op.create_index(
        "ix_retrieval_embeddings_workspace_document",
        "retrieval_embeddings",
        ["workspace_id", "document_id"],
    )
    op.create_index(
        "uq_retrieval_embeddings_source",
        "retrieval_embeddings",
        ["workspace_id", "index_kind", "source_id"],
        unique=True,
    )

    # IVFFLAT ANN index for vector search. ``lists`` is a tuning knob;
    # ~100 is the recommended default for tables up to a few hundred
    # thousand rows. For workspaces in the low thousands the linear
    # scan is fine, but the index keeps the door open as data grows.
    op.execute(
        "CREATE INDEX ix_retrieval_embeddings_embedding "
        "ON retrieval_embeddings USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )

    # ---- chat_eval_runs ---------------------------------------------------
    op.create_table(
        "chat_eval_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dataset_name", sa.Text(), nullable=False),
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column(
            "retrieval_modes",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[\"rag\",\"graph\",\"hybrid\"]'::jsonb"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
            "completed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.CheckConstraint(
            "status IN ('pending','running','complete','failed')",
            name="ck_chat_eval_runs_status",
        ),
    )
    op.create_index(
        "ix_chat_eval_runs_workspace_created",
        "chat_eval_runs",
        ["workspace_id", sa.text("created_at DESC")],
    )

    # ---- chat_eval_questions ---------------------------------------------
    # Snapshotted copy of the dataset question used by a given run, so
    # changing the dataset file later doesn't invalidate historical runs.
    op.create_table(
        "chat_eval_questions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("chat_eval_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_key", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column(
            "expected_answer_patterns",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "expected_entity_ids",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "expected_source_ids",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "refusal_expected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "category IN ('vector','aggregation','multi_hop','refusal')",
            name="ck_chat_eval_questions_category",
        ),
    )
    op.create_index(
        "ix_chat_eval_questions_run", "chat_eval_questions", ["run_id"]
    )

    # ---- chat_eval_results -----------------------------------------------
    # One row per (question, retrieval_mode). Carries the actual answer
    # text + the joined retrieval/chat ids so the comparison UI can
    # cross-link to ``retrieval_records`` and ``chat_citations``.
    op.create_table(
        "chat_eval_results",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("chat_eval_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.Uuid(),
            sa.ForeignKey("chat_eval_questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("retrieval_mode", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("refused", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "chat_message_id",
            sa.Uuid(),
            sa.ForeignKey("chat_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "retrieval_record_id",
            sa.Uuid(),
            sa.ForeignKey("retrieval_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "scores",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "retrieval_mode IN ('rag','graph','hybrid')",
            name="ck_chat_eval_results_retrieval_mode",
        ),
        sa.UniqueConstraint(
            "run_id",
            "question_id",
            "retrieval_mode",
            name="uq_chat_eval_results_per_mode",
        ),
    )
    op.create_index(
        "ix_chat_eval_results_run_mode",
        "chat_eval_results",
        ["run_id", "retrieval_mode"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_eval_results_run_mode", table_name="chat_eval_results")
    op.drop_table("chat_eval_results")
    op.drop_index("ix_chat_eval_questions_run", table_name="chat_eval_questions")
    op.drop_table("chat_eval_questions")
    op.drop_index(
        "ix_chat_eval_runs_workspace_created", table_name="chat_eval_runs"
    )
    op.drop_table("chat_eval_runs")

    op.execute("DROP INDEX IF EXISTS ix_retrieval_embeddings_embedding")
    op.drop_index(
        "uq_retrieval_embeddings_source", table_name="retrieval_embeddings"
    )
    op.drop_index(
        "ix_retrieval_embeddings_workspace_document",
        table_name="retrieval_embeddings",
    )
    op.drop_index(
        "ix_retrieval_embeddings_workspace_kind",
        table_name="retrieval_embeddings",
    )
    op.drop_table("retrieval_embeddings")
    # We intentionally do NOT drop the ``vector`` extension on downgrade
    # because other features (future pgvector use) may depend on it.
