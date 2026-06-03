"""Map an eval result to the full pipeline-stage composition that produced it.

The composable harness compares *compositions*, not just retrieval-mode labels.
Each eval result records the composition (extractor / ontology / graph store /
retrieval strategy / provider) + a content hash, so a metric delta can be
attributed to a specific stage choice (hold-all-vary-one).
"""

from __future__ import annotations

from typing import Any

from app.eval.adapters import normalize_mode
from app.pipeline_stages.base import PipelineConfiguration

# Composition fields that define a stage choice (for attribution / grouping).
STAGE_FIELDS = ("extractor", "ontology_version", "graph_store", "retrieval_strategy", "provider")


def composition_for_mode(mode: str, run_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Full composition for an eval result of the given retrieval mode.

    Non-retrieval stages default to the built-in pipeline (graphiti +
    graphiti_falkor + generic_v1 + cohere_compat) unless the run_config overrides
    them; the retrieval stage is the (normalized) mode.
    """
    rc = run_config or {}
    retrieval = normalize_mode(mode)
    cfg = PipelineConfiguration(
        name=f"eval-{retrieval}",
        extractor=str(rc.get("extractor") or "graphiti"),
        graph_store=str(rc.get("graph_store") or "graphiti_falkor"),
        retrieval_strategy=retrieval,
        ontology_version=str(rc.get("ontology_version") or "generic_v1"),
        provider=str(rc.get("provider") or "cohere_compat"),
    )
    return {**cfg.normalized(), "content_hash": cfg.content_hash}


def diff_stages(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    """Stage fields that differ between two compositions (for attribution).

    When exactly one field differs, a metric delta between the two is
    attributable to that stage.
    """
    return [f for f in STAGE_FIELDS if a.get(f) != b.get(f)]
