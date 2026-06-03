"""GraphRAG community reports + ms_graphrag retrieval mode.

Persists a built GraphRAG index's community reports to Postgres so the
``ms_graphrag`` retrieval strategy (running on the chat-worker, which has no
graphrag/pandas) can read them as grounding for global-search-style answers.
Also extends the retrieval_mode CHECK constraints to allow ``ms_graphrag``.

See specs/openspecs/composable-eval-harness.md and spikes/ms-graphrag/README.md.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_graphrag_community_reports"
down_revision = "0022_graphrag_indexes"
branch_labels = None
depends_on = None

_MSG_MODES = (
    "graph",
    "rag",
    "hybrid",
    "raw_transcript",
    "zettelkasten_notes",
    "amem_lite",
    "ms_graphrag",
)
_EVAL_MODES = _MSG_MODES + ("wiki",)


def _in_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        "graphrag_community_reports",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("graphrag_index_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("community", sa.Integer(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("rank", sa.Float(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("full_content", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["graphrag_index_id"], ["graphrag_indexes.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_graphrag_reports_index",
        "graphrag_community_reports",
        ["graphrag_index_id"],
    )
    op.create_index(
        "ix_graphrag_reports_ws_agent",
        "graphrag_community_reports",
        ["workspace_id", "agent_id"],
    )

    op.drop_constraint("ck_chat_messages_retrieval_mode", "chat_messages", type_="check")
    op.create_check_constraint(
        "ck_chat_messages_retrieval_mode",
        "chat_messages",
        f"retrieval_mode IN ({_in_sql(_MSG_MODES)})",
    )
    op.drop_constraint(
        "ck_chat_eval_results_retrieval_mode", "chat_eval_results", type_="check"
    )
    op.create_check_constraint(
        "ck_chat_eval_results_retrieval_mode",
        "chat_eval_results",
        f"retrieval_mode IN ({_in_sql(_EVAL_MODES)})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_chat_eval_results_retrieval_mode", "chat_eval_results", type_="check")
    op.create_check_constraint(
        "ck_chat_eval_results_retrieval_mode",
        "chat_eval_results",
        "retrieval_mode IN ('graph', 'rag', 'hybrid', 'raw_transcript', "
        "'zettelkasten_notes', 'amem_lite', 'wiki')",
    )
    op.drop_constraint("ck_chat_messages_retrieval_mode", "chat_messages", type_="check")
    op.create_check_constraint(
        "ck_chat_messages_retrieval_mode",
        "chat_messages",
        "retrieval_mode IN ('graph', 'rag', 'hybrid', 'raw_transcript', "
        "'zettelkasten_notes', 'amem_lite')",
    )
    op.drop_index("ix_graphrag_reports_ws_agent", table_name="graphrag_community_reports")
    op.drop_index("ix_graphrag_reports_index", table_name="graphrag_community_reports")
    op.drop_table("graphrag_community_reports")
