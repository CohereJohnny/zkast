"""Per-provider api_keys uniqueness for optional LLM providers.

``api_keys.kind`` is free text; this adds partial unique indexes so each
workspace holds at most one ``llm_openai`` and one ``llm_azure_openai`` key
(mirroring ``uq_api_keys_workspace_llm_cohere``), giving rotate-on-conflict
semantics. No CHECK on ``kind`` exists, so no enum change is needed.

See specs/openspecs/composable-eval-harness.md (configurable LLM provider).
"""

from __future__ import annotations

from alembic import op

revision = "0021_provider_api_keys"
down_revision = "0020_prompt_sets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_api_keys_workspace_llm_openai",
        "api_keys",
        ["workspace_id"],
        unique=True,
        postgresql_where="kind = 'llm_openai'",
    )
    op.create_index(
        "uq_api_keys_workspace_llm_azure_openai",
        "api_keys",
        ["workspace_id"],
        unique=True,
        postgresql_where="kind = 'llm_azure_openai'",
    )


def downgrade() -> None:
    op.drop_index("uq_api_keys_workspace_llm_azure_openai", table_name="api_keys")
    op.drop_index("uq_api_keys_workspace_llm_openai", table_name="api_keys")
