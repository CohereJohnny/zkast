"""Seed harness comparison presets and extend usage_events for GraphRAG builds."""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "0025_harness_presets"
down_revision = "0024_eval_composition"
branch_labels = None
depends_on = None

USAGE_SOURCES = (
    "chat",
    "ingestion",
    "wiki",
    "dream",
    "eval",
    "retrieval",
    "graphrag",
    "other",
)


def _check_in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(repr(v) for v in values) + ")"


def _content_hash(normalized: dict) -> str:
    blob = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _seed_config(
    *,
    name: str,
    description: str,
    extractor: str,
    ontology_version: str | None,
    graph_store: str,
    retrieval_strategy: str,
    params: dict | None = None,
) -> None:
    normalized = {
        "extractor": extractor,
        "graph_store": graph_store,
        "retrieval_strategy": retrieval_strategy,
        "ontology_version": ontology_version,
        "provider": "cohere_compat",
        "params": params or {},
    }
    op.execute(
        sa.text(
            """
            INSERT INTO pipeline_configurations (
              id, workspace_id, name, description, extractor, ontology_version,
              graph_store, retrieval_strategy, provider, params, version,
              content_hash, is_builtin
            )
            SELECT
              gen_random_uuid(), NULL, :name, :description, :extractor, :ontology_version,
              :graph_store, :retrieval_strategy, 'cohere_compat', CAST(:params_json AS jsonb), 1,
              :content_hash, true
            WHERE NOT EXISTS (
              SELECT 1 FROM pipeline_configurations
              WHERE workspace_id IS NULL AND name = :name AND version = 1
            )
            """
        ).bindparams(
            name=name,
            description=description,
            extractor=extractor,
            ontology_version=ontology_version,
            graph_store=graph_store,
            retrieval_strategy=retrieval_strategy,
            params_json=json.dumps(params or {}),
            content_hash=_content_hash(normalized),
        )
    )


def upgrade() -> None:
    op.drop_constraint("ck_usage_events_source", "usage_events", type_="check")
    op.create_check_constraint(
        "ck_usage_events_source",
        "usage_events",
        f"usage_source IN {_check_in(USAGE_SOURCES)}",
    )

    # MS GraphRAG side of fair compare preset.
    _seed_config(
        name="harness-graphiti-vs-graphrag-ms",
        description=(
            "MS GraphRAG arm of fair harness: graphrag extractor + graphrag_artifacts "
            "+ ms_graphrag retrieval (generic_v1 ontology)."
        ),
        extractor="graphrag",
        ontology_version="generic_v1",
        graph_store="graphrag_artifacts",
        retrieval_strategy="ms_graphrag",
        params={"harness_role": "ms_graphrag_fair"},
    )
    # Graphiti baseline (mirrors builtin-default composition for eval attribution).
    _seed_config(
        name="harness-graphiti-vs-graphrag",
        description=(
            "Fair Graphiti vs MS GraphRAG harness: generic_v1 ontology locked on both sides."
        ),
        extractor="graphiti",
        ontology_version="generic_v1",
        graph_store="graphiti_falkor",
        retrieval_strategy="graph",
        params={
            "harness_role": "graphiti_baseline",
            "compare_with": "harness-graphiti-vs-graphrag-ms",
        },
    )
    # Auto-tune preset MS side.
    _seed_config(
        name="harness-graphrag-autotune-ms",
        description=(
            "MS GraphRAG arm with auto-tuned ontology (intentionally unfair vs Graphiti generic)."
        ),
        extractor="graphrag",
        ontology_version="auto_tuned",
        graph_store="graphrag_artifacts",
        retrieval_strategy="ms_graphrag",
        params={"harness_role": "ms_graphrag_autotune"},
    )
    _seed_config(
        name="harness-graphrag-autotune",
        description=(
            "Graphiti generic_v1 vs MS GraphRAG auto-tuned ontology (ontology varies by design)."
        ),
        extractor="graphiti",
        ontology_version="generic_v1",
        graph_store="graphiti_falkor",
        retrieval_strategy="graph",
        params={
            "harness_role": "graphiti_generic",
            "compare_with": "harness-graphrag-autotune-ms",
        },
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM pipeline_configurations
            WHERE workspace_id IS NULL
              AND name IN (
                'harness-graphiti-vs-graphrag',
                'harness-graphiti-vs-graphrag-ms',
                'harness-graphrag-autotune',
                'harness-graphrag-autotune-ms'
              )
            """
        )
    )
    op.drop_constraint("ck_usage_events_source", "usage_events", type_="check")
    op.create_check_constraint(
        "ck_usage_events_source",
        "usage_events",
        "usage_source IN ('chat', 'ingestion', 'wiki', 'dream', 'eval', 'retrieval', 'other')",
    )
