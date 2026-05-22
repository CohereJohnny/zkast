"""Memory eval harness extensions — ability types, top-k cutoffs, run config."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0016_eval_memory_extensions"
down_revision = "0015_wiki_memory"
branch_labels = None
depends_on = None

EVAL_RETRIEVAL_MODES = (
    "graph",
    "rag",
    "hybrid",
    "raw_transcript",
    "zettelkasten_notes",
    "amem_lite",
    "wiki",
)

_MODES_SQL = ", ".join(repr(m) for m in EVAL_RETRIEVAL_MODES)


def upgrade() -> None:
    # ---- chat_eval_runs ---------------------------------------------------
    op.add_column(
        "chat_eval_runs",
        sa.Column(
            "eval_kind",
            sa.Text(),
            nullable=False,
            server_default="chat_retrieval",
        ),
    )
    op.add_column(
        "chat_eval_runs",
        sa.Column("agent_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "chat_eval_runs",
        sa.Column(
            "top_k_cutoffs",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[30]'::jsonb"),
        ),
    )
    op.add_column(
        "chat_eval_runs",
        sa.Column(
            "run_config",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "chat_eval_runs",
        sa.Column("summary", JSONB(), nullable=True),
    )
    op.create_check_constraint(
        "ck_chat_eval_runs_eval_kind",
        "chat_eval_runs",
        "eval_kind IN ('chat_retrieval', 'memory_system')",
    )

    # ---- chat_eval_questions ---------------------------------------------
    op.drop_constraint(
        "ck_chat_eval_questions_category",
        "chat_eval_questions",
        type_="check",
    )
    op.add_column(
        "chat_eval_questions",
        sa.Column("ability_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "chat_eval_questions",
        sa.Column(
            "expected_context_patterns",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # ---- chat_eval_results -----------------------------------------------
    op.add_column(
        "chat_eval_results",
        sa.Column(
            "top_k_cutoff",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )
    op.add_column(
        "chat_eval_results",
        sa.Column("memory_system", sa.Text(), nullable=True),
    )
    op.add_column(
        "chat_eval_results",
        sa.Column("retrieval_items", JSONB(), nullable=True),
    )
    op.add_column(
        "chat_eval_results",
        sa.Column("judge_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "chat_eval_results",
        sa.Column("judge_rationale", sa.Text(), nullable=True),
    )

    op.drop_constraint(
        "ck_chat_eval_results_retrieval_mode",
        "chat_eval_results",
        type_="check",
    )
    op.create_check_constraint(
        "ck_chat_eval_results_retrieval_mode",
        "chat_eval_results",
        f"retrieval_mode IN ({_MODES_SQL})",
    )

    op.drop_constraint(
        "uq_chat_eval_results_per_mode",
        "chat_eval_results",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_chat_eval_results_per_mode_k",
        "chat_eval_results",
        ["run_id", "question_id", "retrieval_mode", "top_k_cutoff"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_chat_eval_results_per_mode_k",
        "chat_eval_results",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_chat_eval_results_per_mode",
        "chat_eval_results",
        ["run_id", "question_id", "retrieval_mode"],
    )

    op.drop_constraint(
        "ck_chat_eval_results_retrieval_mode",
        "chat_eval_results",
        type_="check",
    )
    op.create_check_constraint(
        "ck_chat_eval_results_retrieval_mode",
        "chat_eval_results",
        "retrieval_mode IN ('graph', 'rag', 'hybrid', 'raw_transcript', 'zettelkasten_notes', 'amem_lite')",
    )

    op.drop_column("chat_eval_results", "judge_rationale")
    op.drop_column("chat_eval_results", "judge_score")
    op.drop_column("chat_eval_results", "retrieval_items")
    op.drop_column("chat_eval_results", "memory_system")
    op.drop_column("chat_eval_results", "top_k_cutoff")

    op.drop_column("chat_eval_questions", "expected_context_patterns")
    op.drop_column("chat_eval_questions", "ability_type")
    op.create_check_constraint(
        "ck_chat_eval_questions_category",
        "chat_eval_questions",
        "category IN ('vector','aggregation','multi_hop','refusal')",
    )

    op.drop_constraint("ck_chat_eval_runs_eval_kind", "chat_eval_runs", type_="check")
    op.drop_column("chat_eval_runs", "summary")
    op.drop_column("chat_eval_runs", "run_config")
    op.drop_column("chat_eval_runs", "top_k_cutoffs")
    op.drop_column("chat_eval_runs", "agent_id")
    op.drop_column("chat_eval_runs", "eval_kind")
