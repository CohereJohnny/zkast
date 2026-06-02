"""MS GraphRAG spike runner (graphrag 3.1.0).

Indexes the shared fixture corpus with a chosen provider config and runs a
global + local search, printing results and basic artifact stats. This is an
exploratory spike to learn the integration shape for the real plugin — not
production code.

Usage:
    GRAPHRAG_API_KEY=<key> .venv/bin/python run_spike.py <cohere|openai> ["query"]

Requires network + a valid provider key. See README.md.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pandas as pd

from graphrag.api import build_index, global_search, local_search
from graphrag.config.load_config import load_config

HERE = Path(__file__).resolve().parent
DEFAULT_QUERY = "What are the main themes connecting Acme Power, its vendors, and the standards it follows?"


def _read(out: Path, name: str) -> pd.DataFrame:
    path = out / f"{name}.parquet"
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


async def main(root: str, query: str) -> None:
    root_dir = HERE / root
    config = load_config(root_dir)
    out = root_dir / "output"

    print(f"=== build_index ({root}) ===")
    results = await build_index(config=config, verbose=False)
    for r in results:
        status = "ERROR" if getattr(r, "errors", None) else "ok"
        print(f"  workflow {getattr(r, 'workflow', '?')}: {status}")

    entities = _read(out, "entities")
    relationships = _read(out, "relationships")
    communities = _read(out, "communities")
    community_reports = _read(out, "community_reports")
    text_units = _read(out, "text_units")
    print(
        f"=== artifacts ===\n  entities={len(entities)} relationships={len(relationships)} "
        f"communities={len(communities)} reports={len(community_reports)} text_units={len(text_units)}"
    )

    print("\n=== global_search ===")
    g_resp, _ = await global_search(
        config=config,
        entities=entities,
        communities=communities,
        community_reports=community_reports,
        community_level=2,
        dynamic_community_selection=False,
        response_type="Multiple paragraphs",
        query=query,
    )
    print(g_resp)

    print("\n=== local_search ===")
    l_resp, _ = await local_search(
        config=config,
        entities=entities,
        communities=communities,
        community_reports=community_reports,
        text_units=text_units,
        relationships=relationships,
        covariates=None,
        community_level=2,
        response_type="Multiple paragraphs",
        query=query,
    )
    print(l_resp)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("cohere", "openai"):
        print("usage: run_spike.py <cohere|openai> [query]")
        raise SystemExit(2)
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else DEFAULT_QUERY))
