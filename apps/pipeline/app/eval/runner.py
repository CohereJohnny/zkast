"""Memory eval runner — retrieval mode comparisons with top-k cutoffs."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Json

from app.cohere_chat import CitationSpan, chat_stream_grounded
from app.config import get_settings
from app.eval.adapters import memory_system_for_mode, normalize_mode, retrieval_module
from app.eval.scoring import aggregate_scores, score_answer
from app.graphiti_factory import resolve_cohere_api_key
from app.workspace_repo import fetch_pipeline_settings

logger = logging.getLogger(__name__)

DEFAULT_DATASET = Path(__file__).parent / "datasets" / "oil_gas_v1.yaml"
DEFAULT_MODES: list[str] = ["rag", "graph", "hybrid"]
DEFAULT_TOP_K_CUTOFFS: list[int] = [10, 30]

NORTH_HISTORY_MODES: list[str] = [
    "raw_transcript",
    "zettelkasten_notes",
    "amem_lite",
    "graph",
    "hybrid",
]

RUN_MODES = frozenset({"full", "retrieve_only", "answer_only", "score_only"})


def default_modes_for_dataset(dataset_name: str | None) -> list[str]:
    name = (dataset_name or "").strip().lower()
    if name in ("north_history_v1", "north_history"):
        return list(NORTH_HISTORY_MODES)
    return list(DEFAULT_MODES)


def _load_dataset(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _serialize_retrieved_items(items: list[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items or []:
        if isinstance(item, dict):
            sid = item.get("source_id") or item.get("doc_id") or item.get("id")
            out.append(
                {
                    "source_id": sid,
                    "source_kind": item.get("source_kind") or item.get("kind"),
                    "score": item.get("score"),
                    "excerpt": (item.get("excerpt") or item.get("text") or "")[:500],
                }
            )
            continue
        out.append(
            {
                "source_id": getattr(item, "source_id", None) or getattr(item, "id", None),
                "source_kind": getattr(item, "source_kind", None)
                or getattr(item, "kind", None),
                "score": getattr(item, "score", None),
                "excerpt": (getattr(item, "excerpt", None) or getattr(item, "text", "") or "")[
                    :500
                ],
            }
        )
    return out


def create_eval_run(
    database_url: str,
    *,
    workspace_id: str,
    dataset_name: str,
    dataset_version: str,
    modes: list[str],
    notes: str | None,
    eval_kind: str = "memory_system",
    agent_id: str | None = None,
    top_k_cutoffs: list[int] | None = None,
    run_config: dict[str, Any] | None = None,
) -> str:
    run_id = str(uuid4())
    cutoffs = list(top_k_cutoffs or DEFAULT_TOP_K_CUTOFFS)
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO chat_eval_runs (
                id, workspace_id, dataset_name, dataset_version,
                retrieval_modes, notes, status, eval_kind, agent_id,
                top_k_cutoffs, run_config
            )
            VALUES (
                %s::uuid, %s::uuid, %s, %s,
                %s, %s, 'running', %s, %s::uuid,
                %s, %s
            )
            """,
            (
                run_id,
                workspace_id,
                dataset_name,
                dataset_version,
                Json([normalize_mode(m) for m in modes]),
                notes,
                eval_kind,
                agent_id,
                Json(cutoffs),
                Json(run_config or {}),
            ),
        )
        conn.commit()
    return run_id


def _insert_question(
    conn: psycopg.Connection,
    *,
    run_id: str,
    q: dict[str, Any],
) -> str:
    qid = str(uuid4())
    ability = q.get("ability_type") or q.get("category")
    conn.execute(
        """
        INSERT INTO chat_eval_questions (
            id, run_id, question_key, category, question_text,
            expected_answer_patterns, expected_entity_ids,
            expected_source_ids, refusal_expected, notes,
            ability_type, expected_context_patterns
        )
        VALUES (
            %s::uuid, %s::uuid, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s
        )
        """,
        (
            qid,
            run_id,
            str(q.get("key")),
            str(q.get("category")),
            str(q.get("question_text")),
            Json(list(q.get("expected_answer_patterns") or [])),
            Json(list(q.get("expected_entity_ids") or [])),
            Json(list(q.get("expected_source_ids") or [])),
            bool(q.get("refusal_expected")),
            str(q.get("notes") or ""),
            str(ability) if ability else None,
            Json(list(q.get("expected_context_patterns") or [])),
        ),
    )
    return qid


def _insert_result(
    conn: psycopg.Connection,
    *,
    run_id: str,
    question_id: str,
    mode: str,
    memory_system: str,
    top_k_cutoff: int,
    answer_text: str,
    refused: bool,
    score_summary: dict[str, Any],
    latency_ms: int | None,
    tokens_in: int | None,
    tokens_out: int | None,
    retrieval_items: list[dict[str, Any]] | None,
) -> None:
    conn.execute(
        """
        INSERT INTO chat_eval_results (
            id, run_id, question_id, retrieval_mode, memory_system,
            top_k_cutoff, answer_text, refused, scores, latency_ms,
            tokens_in, tokens_out, retrieval_items
        )
        VALUES (
            %s::uuid, %s::uuid, %s::uuid, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s
        )
        """,
        (
            str(uuid4()),
            run_id,
            question_id,
            normalize_mode(mode),
            memory_system,
            top_k_cutoff,
            answer_text[:20_000],
            bool(refused),
            Json(score_summary),
            latency_ms,
            tokens_in,
            tokens_out,
            Json(retrieval_items) if retrieval_items is not None else None,
        ),
    )


def _finalize_run(
    database_url: str,
    run_id: str,
    status: str,
    summary: dict[str, Any] | None = None,
) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            UPDATE chat_eval_runs
            SET status = %s, completed_at = now(), summary = %s
            WHERE id = %s::uuid
            """,
            (status, Json(summary) if summary else None, run_id),
        )
        conn.commit()


async def _retrieve_only(
    *,
    settings: Any,
    database_url: str,
    workspace_id: str,
    query_text: str,
    mode: str,
    top_k: int,
    doc_token_budget: int,
    agent_id: str | None = None,
) -> dict[str, Any]:
    impl = retrieval_module(mode)
    started = time.perf_counter()
    scope: dict[str, Any] = {}
    if agent_id:
        scope["agent_id"] = agent_id

    (
        retrieved_items,
        documents,
        _total,
        _truncated,
        _strategy,
    ) = await impl.retrieve(
        settings,
        database_url,
        workspace_id=workspace_id,
        query_text=query_text,
        scope=scope,
        top_k=top_k,
        doc_token_budget=doc_token_budget,
    )
    snapshot = _serialize_retrieved_items(retrieved_items)
    refused = not documents
    answer_text = (
        "Refused: workspace lacks grounding context for this question."
        if refused
        else "[retrieve_only] contexts captured without answer generation."
    )
    return {
        "answer_text": answer_text,
        "refused": refused,
        "citations": [],
        "cited_source_kinds": [],
        "cited_source_ids": [],
        "cited_excerpts": [],
        "tokens_in": 0,
        "tokens_out": 0,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "retrieved_items": retrieved_items,
        "retrieval_snapshot": snapshot,
    }


async def _answer_one(
    *,
    settings: Any,
    database_url: str,
    workspace_id: str,
    api_key: str,
    chat_model: str,
    query_text: str,
    mode: str,
    top_k: int,
    doc_token_budget: int,
    agent_id: str | None = None,
) -> dict[str, Any]:
    impl = retrieval_module(mode)
    started = time.perf_counter()

    scope: dict[str, Any] = {}
    if agent_id:
        scope["agent_id"] = agent_id

    (
        retrieved_items,
        documents,
        _total,
        _truncated,
        _strategy,
    ) = await impl.retrieve(
        settings,
        database_url,
        workspace_id=workspace_id,
        query_text=query_text,
        scope=scope,
        top_k=top_k,
        doc_token_budget=doc_token_budget,
    )
    snapshot = _serialize_retrieved_items(retrieved_items)

    if not documents:
        return {
            "answer_text": (
                "Refused: workspace lacks grounding context for this question."
            ),
            "refused": True,
            "citations": [],
            "cited_source_kinds": [],
            "cited_source_ids": [],
            "cited_excerpts": [],
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "retrieved_items": retrieved_items,
            "retrieval_snapshot": snapshot,
        }

    accumulated_text: list[str] = []
    citation_spans: list[CitationSpan] = []

    async def on_token(delta: str) -> None:
        accumulated_text.append(delta)

    async def on_citation(span: CitationSpan) -> None:
        citation_spans.append(span)

    async def on_warning(_msg: str, _data: dict[str, Any] | None) -> None:
        return None

    try:
        result = await chat_stream_grounded(
            api_key=api_key,
            model=chat_model,
            messages=[{"role": "user", "content": query_text}],
            documents=documents,
            on_token=on_token,
            on_citation=on_citation,
            on_warning=on_warning,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "answer_text": f"[eval-error] {type(exc).__name__}: {exc}",
            "refused": False,
            "citations": [],
            "cited_source_kinds": [],
            "cited_source_ids": [],
            "cited_excerpts": [],
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "retrieved_items": retrieved_items,
            "retrieval_snapshot": snapshot,
            "error": True,
        }

    answer_text = result.text or "".join(accumulated_text)
    citations = result.citations or citation_spans

    cited_source_kinds: list[str] = []
    cited_source_ids: list[str] = []
    cited_excerpts: list[str] = []
    for span in citations:
        for sid in span.source_ids or []:
            prefix, _, payload = sid.partition(":")
            cited_source_kinds.append(prefix)
            cited_source_ids.append(sid)
            cited_excerpts.append(span.text or "")
            if payload:
                cited_source_ids.append(payload)

    return {
        "answer_text": answer_text,
        "refused": False,
        "citations": [
            {
                "text_start": s.text_start,
                "text_end": s.text_end,
                "text": s.text,
                "source_ids": list(s.source_ids or []),
            }
            for s in citations
        ],
        "cited_source_kinds": cited_source_kinds,
        "cited_source_ids": cited_source_ids,
        "cited_excerpts": cited_excerpts,
        "tokens_in": result.tokens_in or 0,
        "tokens_out": result.tokens_out or 0,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "retrieved_items": retrieved_items,
        "retrieval_snapshot": snapshot,
    }


async def run_eval(
    *,
    workspace_id: str,
    dataset_path: Path | None = None,
    modes: list[str] | None = None,
    notes: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    top_k_cutoffs: list[int] | None = None,
    run_mode: str = "full",
    eval_kind: str = "memory_system",
    run_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Drive the eval dataset and return ``{run_id, summary, results}``."""
    settings = get_settings()
    database_url = settings.database_url
    ds_path = dataset_path or DEFAULT_DATASET
    modes = [normalize_mode(m) for m in (modes or DEFAULT_MODES)]
    cutoffs = sorted({int(k) for k in (top_k_cutoffs or DEFAULT_TOP_K_CUTOFFS)})
    mode_key = (run_mode or "full").strip().lower()
    if mode_key not in RUN_MODES:
        raise ValueError(f"unknown run_mode: {run_mode!r}")

    dataset = _load_dataset(ds_path)
    questions = list(dataset.get("questions") or [])
    if not questions:
        raise RuntimeError(f"dataset has no questions: {ds_path}")

    api_key = resolve_cohere_api_key(settings, workspace_id)
    if mode_key != "retrieve_only" and not api_key:
        raise RuntimeError("no Cohere API key configured for workspace")

    pipeline_settings = fetch_pipeline_settings(database_url, workspace_id)
    chat_model = pipeline_settings.get("large_model") or "command-a-plus-05-2026"

    cfg = dict(run_config or {})
    cfg.setdefault("run_mode", mode_key)
    cfg.setdefault("top_k_cutoffs", cutoffs)

    if run_id is None:
        run_id = create_eval_run(
            database_url,
            workspace_id=workspace_id,
            dataset_name=str(dataset.get("name") or ds_path.stem),
            dataset_version=str(dataset.get("version") or "1"),
            modes=modes,
            notes=notes,
            eval_kind=eval_kind,
            agent_id=agent_id,
            top_k_cutoffs=cutoffs,
            run_config=cfg,
        )
    else:
        with psycopg.connect(database_url) as conn:
            conn.execute(
                "UPDATE chat_eval_runs SET status = 'running' WHERE id = %s::uuid",
                (run_id,),
            )
            conn.commit()

    rollup_rows: list[dict[str, Any]] = []

    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            for q in questions:
                qid = _insert_question(conn, run_id=run_id, q=q)
                conn.commit()
                ability = q.get("ability_type") or q.get("category")
                for mode in modes:
                    mem_sys = memory_system_for_mode(mode)
                    for top_k in cutoffs:
                        if mode_key == "retrieve_only":
                            res = await _retrieve_only(
                                settings=settings,
                                database_url=database_url,
                                workspace_id=workspace_id,
                                query_text=str(q.get("question_text")),
                                mode=mode,
                                top_k=top_k,
                                doc_token_budget=6000,
                                agent_id=agent_id,
                            )
                        elif mode_key == "score_only":
                            raise NotImplementedError(
                                "score_only requires a prior run with stored results"
                            )
                        else:
                            res = await _answer_one(
                                settings=settings,
                                database_url=database_url,
                                workspace_id=workspace_id,
                                api_key=api_key or "",
                                chat_model=chat_model,
                                query_text=str(q.get("question_text")),
                                mode=mode,
                                top_k=top_k,
                                doc_token_budget=6000,
                                agent_id=agent_id,
                            )

                        sc = score_answer(
                            answer_text=res["answer_text"],
                            refused=res["refused"],
                            expected_answer_patterns=list(
                                q.get("expected_answer_patterns") or []
                            ),
                            expected_entity_names=list(
                                q.get("expected_entity_ids") or []
                            ),
                            cited_source_kinds=res.get("cited_source_kinds", []),
                            cited_source_ids=res.get("cited_source_ids", []),
                            cited_excerpts=res.get("cited_excerpts", []),
                            refusal_expected=bool(q.get("refusal_expected")),
                            expected_source_ids=list(q.get("expected_source_ids") or []),
                            expected_context_patterns=list(
                                q.get("expected_context_patterns") or []
                            ),
                            retrieved_items=res.get("retrieved_items"),
                        )
                        _insert_result(
                            conn,
                            run_id=run_id,
                            question_id=qid,
                            mode=mode,
                            memory_system=mem_sys,
                            top_k_cutoff=top_k,
                            answer_text=res["answer_text"],
                            refused=res["refused"],
                            score_summary=sc.summary,
                            latency_ms=res.get("latency_ms"),
                            tokens_in=res.get("tokens_in"),
                            tokens_out=res.get("tokens_out"),
                            retrieval_items=res.get("retrieval_snapshot"),
                        )
                        conn.commit()
                        rollup_rows.append(
                            {
                                "mode": mode,
                                "memory_system": mem_sys,
                                "category": q.get("category"),
                                "ability_type": ability,
                                "question_key": q.get("key"),
                                "top_k_cutoff": top_k,
                                "pattern_match": sc.pattern_match,
                                "citation_recall": sc.citation_recall,
                                "context_recall": sc.context_recall,
                                "refusal_correct": sc.refusal_correct,
                                "latency_ms": res.get("latency_ms"),
                                "tokens_in": res.get("tokens_in"),
                                "tokens_out": res.get("tokens_out"),
                                "refused": res["refused"],
                            }
                        )
                        print(
                            f"[eval {run_id[:8]}] {ability}/{q.get('key')} "
                            f"mode={mode} k={top_k} pattern={sc.pattern_match} "
                            f"ctx={sc.context_recall:.2f} recall={sc.citation_recall:.2f}"
                        )
    except Exception:
        _finalize_run(database_url, run_id, "failed")
        raise

    summary = aggregate_scores(rollup_rows)
    _finalize_run(database_url, run_id, "complete", summary=summary)
    return {"run_id": run_id, "summary": summary, "results": rollup_rows}


# Backward-compatible alias used by internal_eval imports.
_retrieval_module = retrieval_module


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="zkast-eval",
        description="Run the memory-system eval suite.",
    )
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--modes", default="rag,graph,hybrid")
    parser.add_argument("--notes", default=None)
    parser.add_argument("--agent-id", default=None)
    parser.add_argument("--top-k", default="10,30", help="Comma-separated top-k cutoffs.")
    parser.add_argument(
        "--run-mode",
        default="full",
        choices=sorted(RUN_MODES),
    )
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset) if args.dataset else None
    if dataset_path and not dataset_path.is_absolute():
        candidate = Path(__file__).parent / "datasets" / dataset_path.name
        if candidate.is_file():
            dataset_path = candidate
    modes = [m.strip() for m in (args.modes or "").split(",") if m.strip()]
    if args.modes == "rag,graph,hybrid" and dataset_path:
        modes = default_modes_for_dataset(dataset_path.stem)
    cutoffs = [int(x) for x in args.top_k.split(",") if x.strip()]
    summary = asyncio.run(
        run_eval(
            workspace_id=args.workspace_id,
            dataset_path=dataset_path,
            modes=modes,
            notes=args.notes,
            agent_id=args.agent_id,
            top_k_cutoffs=cutoffs,
            run_mode=args.run_mode,
        )
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
