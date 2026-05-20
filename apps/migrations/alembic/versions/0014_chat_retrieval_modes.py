"""Allow North-history and note-vector retrieval modes on chat_messages."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_chat_retrieval_modes"
down_revision = "0013_episode_content_hash"
branch_labels = None
depends_on = None

CHAT_RETRIEVAL_MODES = (
    "graph",
    "rag",
    "hybrid",
    "raw_transcript",
    "zettelkasten_notes",
    "amem_lite",
)

_MODES_SQL = ", ".join(repr(m) for m in CHAT_RETRIEVAL_MODES)


def upgrade() -> None:
    op.drop_constraint("ck_chat_messages_retrieval_mode", "chat_messages", type_="check")
    op.create_check_constraint(
        "ck_chat_messages_retrieval_mode",
        "chat_messages",
        f"retrieval_mode IN ({_MODES_SQL})",
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


def downgrade() -> None:
    op.drop_constraint("ck_chat_eval_results_retrieval_mode", "chat_eval_results", type_="check")
    op.create_check_constraint(
        "ck_chat_eval_results_retrieval_mode",
        "chat_eval_results",
        "retrieval_mode IN ('rag', 'graph', 'hybrid')",
    )

    op.drop_constraint("ck_chat_messages_retrieval_mode", "chat_messages", type_="check")
    op.create_check_constraint(
        "ck_chat_messages_retrieval_mode",
        "chat_messages",
        "retrieval_mode IN ('graph', 'rag', 'hybrid')",
    )
