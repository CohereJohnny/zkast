"""Sprint 6b — headless eval runner.

The runner exercises the production retrieval modules
(``chat_retrieval_raw``, ``chat_retrieval_graph``,
``chat_retrieval_hybrid``) and Cohere chat directly. It bypasses arq /
SSE because (a) the eval is run offline by humans, (b) the arq scheduler
adds 5–8 s of layout time per turn for nothing, and (c) the production
chat tests already cover the arq pipeline.

Public API:

- ``run_eval(workspace_id, dataset_path, modes, notes)`` — load the
  dataset, run every (question, mode) pair, persist eval rows, return
  the run id + aggregate summary.

For each question the runner:

1. Calls the matching ``chat_retrieval_*.retrieve``.
2. Calls ``cohere_chat.chat_stream_grounded`` with the retrieved
   documents — same path as the live chat turn.
3. Captures answer text, citations, retrieval-record snapshot, token
   counts, latency.
4. Scores the result via ``eval.scoring`` and persists the row.
"""

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

from types import SimpleNamespace

from app import (
    chat_retrieval_graph,
    chat_retrieval_hybrid,
    chat_retrieval_raw,
)
from app.chat_retrieval_notes_vector import retrieve_amem, retrieve_zettel
from app.cohere_chat import (
    ChatDocument,
    CitationSpan,
    chat_stream_grounded,
)
from app.config import get_settings
from app.eval.scoring import aggregate_scores, score_answer
from app.graphiti_factory import resolve_cohere_api_key
from app.workspace_repo import fetch_pipeline_settings

logger = logging.getLogger(__name__)


DEFAULT_DATASET = (
    Path(__file__).parent / "datasets" / "oil_gas_v1.yaml"
)

DEFAULT_MODES: list[str] = ["rag", "graph", "hybrid"]


def _retrieval_module(mode: str) -> Any:
    m = (mode or "").strip().lower()
    if m in ("rag", "raw_transcript"):
        return chat_retrieval_raw
    if m == "graph":
        return chat_retrieval_graph
    if m == "hybrid":
        return chat_retrieval_hybrid
    if m in ("zettelkasten_notes", "zettelkasten"):
        return SimpleNamespace(retrieve=retrieve_zettel)
    if m in ("amem_lite", "amem"):
        return SimpleNamespace(retrieve=retrieve_amem)
    raise ValueError(f"unknown retrieval mode: {mode!r}")


def _load_dataset(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _create_run(
    database_url: str,
    *,
    workspace_id: str,
    dataset_name: str,
    dataset_version: str,
    modes: list[str],
    notes: str | None,
) -> str:
    run_id = str(uuid4())
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            INSERT INTO chat_eval_runs (
                id, workspace_id, dataset_name, dataset_version,
                retrieval_modes, notes, status
            )
            VALUES (
                %s::uuid, %s::uuid, %s, %s,
                %s, %s, 'running'
            )
            """,
            (
                run_id,
                workspace_id,
                dataset_name,
                dataset_version,
                Json(list(modes)),
                notes,
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
    conn.execute(
        """
        INSERT INTO chat_eval_questions (
            id, run_id, question_key, category, question_text,
            expected_answer_patterns, expected_entity_ids,
            expected_source_ids, refusal_expected, notes
        )
        VALUES (
            %s::uuid, %s::uuid, %s, %s, %s,
            %s, %s, %s, %s, %s
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
        ),
    )
    return qid


def _insert_result(
    conn: psycopg.Connection,
    *,
    run_id: str,
    question_id: str,
    mode: str,
    answer_text: str,
    refused: bool,
    score_summary: dict[str, Any],
    latency_ms: int | None,
    tokens_in: int | None,
    tokens_out: int | None,
) -> None:
    conn.execute(
        """
        INSERT INTO chat_eval_results (
            id, run_id, question_id, retrieval_mode,
            answer_text, refused, scores, latency_ms, tokens_in, tokens_out
        )
        VALUES (
            %s::uuid, %s::uuid, %s::uuid, %s,
            %s, %s, %s, %s, %s, %s
        )
        """,
        (
            str(uuid4()),
            run_id,
            question_id,
            mode,
            answer_text[:20_000],
            bool(refused),
            Json(score_summary),
            latency_ms,
            tokens_in,
            tokens_out,
        ),
    )


def _finalize_run(database_url: str, run_id: str, status: str) -> None:
    with psycopg.connect(database_url) as conn:
        conn.execute(
            """
            UPDATE chat_eval_runs
            SET status = %s, completed_at = now()
            WHERE id = %s::uuid
            """,
            (status, run_id),
        )
        conn.commit()


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
    """Run retrieval + Cohere for one (question, mode). Returns a dict
    with ``answer_text``, ``refused``, ``citations``, ``tokens_in``,
    ``tokens_out``, ``latency_ms``."""
    impl = _retrieval_module(mode)
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

    if not documents:
        return {
            "answer_text": (
                "Refused: workspace lacks grounding context for this question."
            ),
            "refused": True,
            "citations": [],
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "retrieved_items": retrieved_items,
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
            "tokens_in": 0,
            "tokens_out": 0,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "retrieved_items": retrieved_items,
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
    }


async def run_eval(
    *,
    workspace_id: str,
    dataset_path: Path | None = None,
    modes: list[str] | None = None,
    notes: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Drive the canned eval and return ``{run_id, summary, results}``.

    Persists to ``chat_eval_runs`` / ``chat_eval_questions`` /
    ``chat_eval_results`` and prints a one-line summary per question
    so a CLI invocation gives live feedback.
    """
    settings = get_settings()
    database_url = settings.database_url
    ds_path = dataset_path or DEFAULT_DATASET
    modes = list(modes or DEFAULT_MODES)
    dataset = _load_dataset(ds_path)
    questions = list(dataset.get("questions") or [])
    if not questions:
        raise RuntimeError(f"dataset has no questions: {ds_path}")

    api_key = resolve_cohere_api_key(settings, workspace_id)
    if not api_key:
        raise RuntimeError("no Cohere API key configured for workspace")

    pipeline_settings = fetch_pipeline_settings(database_url, workspace_id)
    chat_model = (
        pipeline_settings.get("large_model")
        or "command-a-plus-05-2026"
    )

    run_id = _create_run(
        database_url,
        workspace_id=workspace_id,
        dataset_name=str(dataset.get("name") or ds_path.stem),
        dataset_version="1",
        modes=modes,
        notes=notes,
    )
    rollup_rows: list[dict[str, Any]] = []

    try:
        with psycopg.connect(database_url, row_factory=dict_row) as conn:
            for q in questions:
                qid = _insert_question(conn, run_id=run_id, q=q)
                conn.commit()
                for mode in modes:
                    res = await _answer_one(
                        settings=settings,
                        database_url=database_url,
                        workspace_id=workspace_id,
                        api_key=api_key,
                        chat_model=chat_model,
                        query_text=str(q.get("question_text")),
                        mode=mode,
                        top_k=30,
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
                    )
                    _insert_result(
                        conn,
                        run_id=run_id,
                        question_id=qid,
                        mode=mode,
                        answer_text=res["answer_text"],
                        refused=res["refused"],
                        score_summary=sc.summary,
                        latency_ms=res.get("latency_ms"),
                        tokens_in=res.get("tokens_in"),
                        tokens_out=res.get("tokens_out"),
                    )
                    conn.commit()
                    rollup_rows.append(
                        {
                            "mode": mode,
                            "category": q.get("category"),
                            "question_key": q.get("key"),
                            "pattern_match": sc.pattern_match,
                            "citation_recall": sc.citation_recall,
                            "refusal_correct": sc.refusal_correct,
                            "latency_ms": res.get("latency_ms"),
                            "tokens_in": res.get("tokens_in"),
                            "tokens_out": res.get("tokens_out"),
                            "refused": res["refused"],
                        }
                    )
                    print(
                        f"[eval {run_id[:8]}] {q.get('category')}/{q.get('key')} "
                        f"mode={mode} pattern_match={sc.pattern_match} "
                        f"recall={sc.citation_recall:.2f} "
                        f"refusal_correct={sc.refusal_correct} "
                        f"latency_ms={res.get('latency_ms')}"
                    )
    except Exception:
        _finalize_run(database_url, run_id, "failed")
        raise

    _finalize_run(database_url, run_id, "complete")
    summary = aggregate_scores(rollup_rows)
    return {"run_id": run_id, "summary": summary, "results": rollup_rows}


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ``python -m app.eval.runner --workspace-id <uuid>``."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="zkast-eval",
        description="Run the Sprint 6b GraphRAG vs Naive RAG eval suite.",
    )
    parser.add_argument(
        "--workspace-id", required=True, help="UUID of the workspace to eval against."
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="YAML dataset path. Defaults to oil_gas_v1.yaml.",
    )
    parser.add_argument(
        "--modes",
        default="rag,graph,hybrid",
        help="Comma-separated retrieval modes to evaluate.",
    )
    parser.add_argument(
        "--notes", default=None, help="Free-form notes attached to the run."
    )
    parser.add_argument(
        "--agent-id",
        default=None,
        help="Optional North agent UUID to scope Naive-RAG raw retrieval.",
    )

    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset) if args.dataset else None
    modes = [m.strip() for m in (args.modes or "").split(",") if m.strip()]
    summary = asyncio.run(
        run_eval(
            workspace_id=args.workspace_id,
            dataset_path=dataset_path,
            modes=modes,
            notes=args.notes,
            agent_id=args.agent_id,
        )
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
