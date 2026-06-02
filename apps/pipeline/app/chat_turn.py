"""Sprint 6 — Grounded chat turn orchestration.

The :func:`run_chat_turn` task is the single entry point for one user → one
assistant turn. It is enqueued by ``internal_chat.post_message`` and runs
under arq with the timeout / cancellation pattern shipped in Sprint 5b
(see [`apps/pipeline/app/tasks.py`](apps/pipeline/app/tasks.py)).

Hard invariants:

1. **FR-41**: The ``retrieval_records`` row is written *before* the first
   Cohere call. Tests pin this.
2. **Refusal path**: empty retrieval → assistant message ends at
   ``status='refused'`` with no Cohere call (FR-45).
3. **Cancellation**: a worker shutdown or arq job-timeout raises
   ``CancelledError`` which is caught, classified, and re-raised after
   marking the message ``cancelled``.
4. **Empty stream**: Cohere stream returning zero content deltas
   falls back to a non-streaming call once, surfacing a ``warning``
   log event into the drawer (BUG-009 pattern).

The seven SSE event types this task emits are documented in
[`specs/apis.md`](../../../specs/apis.md) under ``GET /jobs/{id}/events``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import structlog

from app.chat_repo import (
    fetch_message,
    fetch_session,
    insert_citation_rows,
    list_messages_for_session,
    patch_session,
    update_assistant_message,
)
from app.cohere_chat import (
    ChatDocument,
    CitationSpan,
    chat_stream_grounded,
)
from app.config import get_settings
from app.filter_options_repo import summarize_workspace_graph
from app.graphiti_factory import (
    graphiti_for_workspace,
    resolve_cohere_api_key,
)
from app.job_redis import (
    job_hset,
    publish_job_event,
    record_log,
    record_metric,
)
from app.retrieval_repo import insert_retrieval_record
from app.workspace_repo import fetch_pipeline_settings

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------


DEFAULT_TOP_K = 30
DEFAULT_DOC_TOKEN_BUDGET = 6_000  # very rough — Cohere counts differ
HISTORY_LIMIT = 20
APPROX_CHARS_PER_TOKEN = 4  # for the doc-token budget heuristic


# ---------------------------------------------------------------------------
# Public arq task
# ---------------------------------------------------------------------------


async def run_chat_turn(
    ctx: dict[str, Any],
    *,
    workspace_id: str,
    session_id: str,
    user_message_id: str,
    assistant_message_id: str,
    turn_id: str,
) -> None:
    """Execute one grounded chat turn end-to-end.

    All seven SSE events fan out through ``publish_job_event`` /
    ``record_log`` on the per-job Redis pub/sub channel + Stream
    (``zkast:jobs:<turn_id>``), so the existing ``JobLogConsole`` drawer
    also shows chat-turn activity when subscribed.
    """
    redis = ctx["redis"]
    database_url: str = ctx["database_url"]
    settings = get_settings()

    started_at = asyncio.get_event_loop().time()

    await job_hset(
        redis,
        turn_id,
        status="running",
        kind="chat_turn",
        workspace_id=workspace_id,
        session_id=session_id,
        assistant_message_id=assistant_message_id,
        progress=json.dumps({"percent": 0, "stage": "chat_turn"}),
    )
    await publish_job_event(redis, turn_id, "stage_started", stage="chat_turn")

    try:
        session = await asyncio.to_thread(
            fetch_session,
            database_url,
            workspace_id=workspace_id,
            session_id=session_id,
        )
        if not session:
            raise RuntimeError("chat session not found")

        user_msg = await asyncio.to_thread(
            fetch_message, database_url, message_id=user_message_id
        )
        if not user_msg or user_msg.get("role") != "user":
            raise RuntimeError("user message not found or not a user message")

        history = await asyncio.to_thread(
            list_messages_for_session,
            database_url,
            session_id=session_id,
            limit=HISTORY_LIMIT,
        )

        api_key = await asyncio.to_thread(
            resolve_cohere_api_key, settings, workspace_id
        )
        if not api_key:
            raise RuntimeError("No Cohere API key configured for this workspace")

        pipeline_settings = await asyncio.to_thread(
            fetch_pipeline_settings, database_url, workspace_id
        )
        model_settings = dict(session.get("model_settings") or {})
        chat_model = (
            model_settings.get("chat_model")
            or pipeline_settings.get("large_model")
            or "command-a-plus-05-2026"
        )
        top_k = int(model_settings.get("top_k") or DEFAULT_TOP_K)
        doc_token_budget = int(
            model_settings.get("doc_token_budget")
            or pipeline_settings.get("chat_doc_token_budget")
            or DEFAULT_DOC_TOKEN_BUDGET
        )

        # ---- Retrieval ----
        query_text = user_msg.get("content") or ""
        # Sprint 6b: explicit retrieval_mode dispatch. Session scope can
        # override the default via ``model_settings.retrieval_mode``;
        # otherwise we fall back to ``chat_messages.retrieval_mode`` for
        # this turn (set when the row is inserted). ``graph`` stays the
        # default for backwards compatibility with Sprint 6.
        retrieval_mode = (
            (model_settings.get("retrieval_mode") or "").strip().lower()
            or (str(user_msg.get("retrieval_mode") or "").strip().lower() or None)
            or "graph"
        )
        if retrieval_mode not in {
            "rag",
            "raw_transcript",
            "graph",
            "hybrid",
            "zettelkasten_notes",
            "amem_lite",
        }:
            retrieval_mode = "graph"
        await publish_job_event(
            redis,
            turn_id,
            "retrieval_started",
            query_text=query_text[:1000],
            retrieval_mode=retrieval_mode,
        )

        (
            retrieved_items,
            documents,
            total_candidates,
            truncated,
            retrieval_strategy,
        ) = await _retrieve(
            settings,
            database_url,
            workspace_id=workspace_id,
            query_text=query_text,
            scope=dict(session.get("scope") or {}),
            top_k=top_k,
            doc_token_budget=doc_token_budget,
            retrieval_mode=retrieval_mode,
        )

        await record_log(
            redis,
            job_id=turn_id,
            level="info" if documents else "warning",
            stage="chat_turn",
            message=(
                f"retrieval mode={retrieval_mode} strategy={retrieval_strategy} "
                f"candidates={total_candidates} kept={len(documents)}"
            ),
            data={
                "retrieval_mode": retrieval_mode,
                "retrieval_strategy": retrieval_strategy,
                "total_candidates": total_candidates,
                "kept": len(documents),
                "truncated": truncated,
            },
            database_url=None,
            ingestion_run_id=None,
        )

        # ---- Persist RetrievalRecord BEFORE the LLM call (FR-41) ----
        retrieval_record_id = await asyncio.to_thread(
            insert_retrieval_record,
            database_url,
            workspace_id=workspace_id,
            message_id=assistant_message_id,
            retrieval_strategy=retrieval_strategy,
            query_text=query_text,
            retrieved_items=retrieved_items,
            total_candidates=total_candidates,
            truncated=truncated,
            scope=dict(session.get("scope") or {}),
        )
        await publish_job_event(
            redis,
            turn_id,
            "retrieval_complete",
            retrieval_record_id=retrieval_record_id,
            total_candidates=total_candidates,
            kept=len(documents),
            truncated=truncated,
        )
        await record_metric(
            redis,
            job_id=turn_id,
            name="retrieved_documents",
            value=len(documents),
            stage="chat_turn",
        )

        # ---- Refusal short-circuit (FR-45) ----
        #
        # ``documents`` may contain only the synthetic ``graph_context``
        # document when the hybrid ranker found zero fact-level hits —
        # that's still enough to answer aggregate / "what's in this
        # workspace" style questions, so we only refuse when there is
        # truly nothing to ground on (empty workspace, where the
        # graph-context render itself returned an empty string and was
        # skipped).
        if not documents:
            refusal_text = (
                "I could not find anything in this workspace to ground an answer. "
                "Try uploading a related PDF or broadening the session scope."
            )
            await asyncio.to_thread(
                update_assistant_message,
                database_url,
                message_id=assistant_message_id,
                content=refusal_text,
                status="refused",
                completed_now=True,
            )
            await asyncio.to_thread(
                patch_session,
                database_url,
                workspace_id=workspace_id,
                session_id=session_id,
                last_activity_at_now=True,
            )
            await publish_job_event(
                redis,
                turn_id,
                "message_complete",
                message_id=assistant_message_id,
                finish_reason="refused",
            )
            await publish_job_event(
                redis, turn_id, "stage_completed", stage="chat_turn"
            )
            await publish_job_event(
                redis, turn_id, "job_completed", status="succeeded"
            )
            await job_hset(
                redis,
                turn_id,
                status="succeeded",
                progress=json.dumps({"percent": 100, "stage": "refused"}),
            )
            return

        # ---- Mark message streaming ----
        await asyncio.to_thread(
            update_assistant_message,
            database_url,
            message_id=assistant_message_id,
            status="streaming",
        )

        # ---- Build Cohere messages from history + current user turn ----
        cohere_messages = _build_chat_messages(history, query_text)

        # ---- Callbacks ----
        accumulated_text_parts: list[str] = []
        citation_rows: list[dict[str, Any]] = []

        async def on_token(delta: str) -> None:
            accumulated_text_parts.append(delta)
            await publish_job_event(redis, turn_id, "token", delta=delta)

        async def on_citation(span: CitationSpan) -> None:
            sources = _map_source_ids_to_sources(span.source_ids, documents)
            row = {
                "text_start": span.text_start,
                "text_end": span.text_end,
                "sources": sources,
            }
            citation_rows.append(row)
            await publish_job_event(
                redis,
                turn_id,
                "citation",
                text_start=span.text_start,
                text_end=span.text_end,
                text=span.text,
                sources=sources,
            )

        async def on_warning(message: str, data: dict[str, Any] | None) -> None:
            await record_log(
                redis,
                job_id=turn_id,
                level="warning",
                stage="chat_turn",
                message=message,
                data=data,
                database_url=None,
                ingestion_run_id=None,
            )

        # ---- Stream from Cohere ----
        result = await chat_stream_grounded(
            api_key=api_key,
            model=chat_model,
            messages=cohere_messages,
            documents=documents,
            on_token=on_token,
            on_citation=on_citation,
            on_warning=on_warning,
        )

        # When Cohere's *stream* returns no content, ``chat_stream_grounded``
        # transparently falls back to a non-streaming call — but that path emits
        # no ``token`` events, so the client (which renders from token deltas)
        # would show an empty bubble / spinner forever. Push the whole answer as
        # a single token so the UI renders the completed text.
        if not accumulated_text_parts and (result.text or "").strip():
            await on_token(result.text)

        # ---- Bulk-insert any citations the SDK emitted only on the final
        # (non-streaming) response. on_citation already accumulates the
        # streamed ones into citation_rows, but the non-streaming code path
        # populates result.citations directly without firing callbacks. ----
        if result.citations and not citation_rows:
            for span in result.citations:
                sources = _map_source_ids_to_sources(span.source_ids, documents)
                citation_rows.append(
                    {
                        "text_start": span.text_start,
                        "text_end": span.text_end,
                        "sources": sources,
                    }
                )

        # ---- Persist citations ----
        if citation_rows:
            await asyncio.to_thread(
                insert_citation_rows,
                database_url,
                message_id=assistant_message_id,
                rows=citation_rows,
            )

        # ---- Finalize ----
        final_text = result.text or "".join(accumulated_text_parts)
        # ``finish_reason='refused'`` is set by ``cohere_chat`` when the
        # model returns a policy refusal (e.g. 422
        # NO_VALID_RESPONSE_GENERATED). Persist that as ``status='refused'``
        # so the UI renders the amber "Refused" badge rather than a green
        # "Complete" with an empty body.
        final_status = (
            "refused" if (result.finish_reason or "").lower() == "refused" else "complete"
        )
        await asyncio.to_thread(
            update_assistant_message,
            database_url,
            message_id=assistant_message_id,
            content=final_text,
            status=final_status,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            completed_now=True,
        )
        scope_agent = str((session.get("scope") or {}).get("agent_id") or "").strip() or None
        if result.tokens_in or result.tokens_out:
            from app.usage_events_repo import insert_usage_event

            await asyncio.to_thread(
                insert_usage_event,
                database_url,
                workspace_id=workspace_id,
                usage_source="chat",
                tokens_in=result.tokens_in or 0,
                tokens_out=result.tokens_out or 0,
                agent_id=scope_agent,
                stage="chat_turn",
                model=chat_model,
                metadata={
                    "session_id": session_id,
                    "message_id": assistant_message_id,
                },
            )
        await asyncio.to_thread(
            patch_session,
            database_url,
            workspace_id=workspace_id,
            session_id=session_id,
            last_activity_at_now=True,
        )
        await publish_job_event(
            redis,
            turn_id,
            "message_complete",
            message_id=assistant_message_id,
            finish_reason=result.finish_reason or "complete",
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            citation_count=len(citation_rows),
        )
        await publish_job_event(redis, turn_id, "stage_completed", stage="chat_turn")
        await publish_job_event(redis, turn_id, "job_completed", status="succeeded")
        await job_hset(
            redis,
            turn_id,
            status="succeeded",
            progress=json.dumps({"percent": 100, "stage": "complete"}),
        )

    except asyncio.CancelledError:
        # Mirror tasks.py pattern — classify, mark failed, re-raise.
        from app.tasks import _classify_cancel_reason

        reason, extra = _classify_cancel_reason(
            "chat_turn", asyncio.get_event_loop().time() - started_at
        )
        try:
            await asyncio.to_thread(
                update_assistant_message,
                database_url,
                message_id=assistant_message_id,
                status="cancelled",
                failure_reason=reason,
                completed_now=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "chat_turn_cancel_update_failed", message_id=assistant_message_id
            )
        await publish_job_event(
            redis,
            turn_id,
            "job_cancelled",
            reason=reason,
            **extra,
        )
        await job_hset(
            redis,
            turn_id,
            status="cancelled",
            progress=json.dumps(
                {"percent": 0, "stage": "chat_turn", "error": reason}
            ),
        )
        raise
    except Exception as exc:  # noqa: BLE001
        from app.tasks import _describe_exception

        reason = _describe_exception(exc)
        logger.exception("chat_turn_failed", turn_id=turn_id, error=reason)
        try:
            await asyncio.to_thread(
                update_assistant_message,
                database_url,
                message_id=assistant_message_id,
                status="failed",
                failure_reason=reason,
                completed_now=True,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "chat_turn_failure_update_failed", message_id=assistant_message_id
            )
        await publish_job_event(redis, turn_id, "job_failed", reason=reason)
        await job_hset(
            redis,
            turn_id,
            status="failed",
            progress=json.dumps(
                {"percent": 0, "stage": "chat_turn", "error": reason}
            ),
        )


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


async def _retrieve(
    settings: Any,
    database_url: str,
    *,
    workspace_id: str,
    query_text: str,
    scope: dict[str, Any],
    top_k: int,
    doc_token_budget: int,
    retrieval_mode: str = "graph",
) -> tuple[list[dict[str, Any]], list[ChatDocument], int, bool, str]:
    """Dispatch the retrieval strategy for one chat turn.

    Returns ``(retrieved_items, documents, total_candidates, truncated,
    retrieval_strategy)`` — the strategy string goes into
    ``retrieval_records.retrieval_strategy`` so the eval / comparison
    UI can group results by strategy.

    The three strategies are strictly isolated by design (BUG-013 +
    TD-015):

    - ``rag`` (Naive RAG): raw parsed-document chunks only via
      ``chat_retrieval_raw``. Forbidden from touching atomic notes,
      entities, relationships, the graph-context document, Graphiti, or
      graph traversal.
    - ``graph`` (Sprint 6 GraphRAG): Graphiti hybrid search over
      zettelkasten-derived artifacts plus the graph-context grounding
      document via ``chat_retrieval_graph``.
    - ``hybrid`` (GraphRAG + deterministic traversal): TD-015 typed and
      multi-hop handlers + supporting graph evidence via
      ``chat_retrieval_hybrid``.
    """
    from app import chat_retrieval_graph as graph_strategy
    from app import chat_retrieval_hybrid as hybrid_strategy
    from app import chat_retrieval_raw as raw_strategy
    from app.chat_retrieval_notes_vector import retrieve_amem, retrieve_zettel

    mode = (retrieval_mode or "graph").strip().lower()
    if mode in ("rag", "raw_transcript"):
        impl = raw_strategy
    elif mode == "hybrid":
        impl = hybrid_strategy
    elif mode == "zettelkasten_notes":
        impl = SimpleNamespace(retrieve=retrieve_zettel)
    elif mode == "amem_lite":
        impl = SimpleNamespace(retrieve=retrieve_amem)
    else:
        impl = graph_strategy

    return await impl.retrieve(
        settings,
        database_url,
        workspace_id=workspace_id,
        query_text=query_text,
        scope=scope,
        top_k=top_k,
        doc_token_budget=doc_token_budget,
    )


# Re-export the graph-context render helper so the existing test
# ``test_chat_graph_context.py`` keeps importing it from this module
# after the Sprint 6b refactor.
from app.chat_retrieval_graph import (  # noqa: E402
    _render_graph_context_document as _render_graph_context_document,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_chat_messages(
    history: list[dict[str, Any]], current_user_text: str
) -> list[dict[str, str]]:
    """Translate prior messages + the current user turn into Cohere v2
    ``messages``.

    History is ordered by ``sequence``; we keep the most recent
    ``HISTORY_LIMIT`` messages and skip the freshly-inserted pending
    assistant placeholder.
    """
    out: list[dict[str, str]] = []
    for msg in history:
        if msg.get("status") in {"pending", "streaming"}:
            continue
        role = msg.get("role") or "user"
        if role not in {"user", "assistant", "system"}:
            continue
        content = msg.get("content") or ""
        if not content.strip():
            continue
        out.append({"role": role, "content": content})
    # Replace the trailing user message (which is already in history with
    # status=complete) with the canonical query so we don't double-send.
    if out and out[-1]["role"] == "user" and out[-1]["content"] == current_user_text:
        return out
    out.append({"role": "user", "content": current_user_text})
    return out


def _map_source_ids_to_sources(
    source_ids: list[str], documents: list[ChatDocument]
) -> list[dict[str, Any]]:
    """Translate Cohere citation ``source_ids`` into ``chat_citations.sources`` entries.

    Source ids are prefixed (``note:<uuid>``, ``entity:<uuid>``,
    ``relationship:<uuid>``, ``episode:<uuid>``) per the convention in
    ``_retrieve`` so the reverse map is deterministic.
    """
    by_id = {d.id: d for d in documents}
    out: list[dict[str, Any]] = []
    for raw in source_ids:
        prefix, _, payload = raw.partition(":")
        if not payload:
            out.append({"kind": "unknown", "id": raw, "excerpt": ""})
            continue
        doc = by_id.get(raw)
        excerpt = (doc.text[:500] if doc else "")
        out.append(
            {
                "kind": prefix,
                "id": payload,
                "document_id": None,
                "page_start": None,
                "page_end": None,
                "excerpt": excerpt,
            }
        )
    return out


def _str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    if isinstance(v, (list, tuple)):
        return [str(s).strip() for s in v if str(s).strip()]
    return []


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _parse_iso(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _temporally_overlaps(
    target: datetime,
    valid_from: Any,
    valid_to: Any,
) -> bool:
    vf = _parse_iso(valid_from)
    vt = _parse_iso(valid_to)
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    if vf and target < vf:
        return False
    if vt and target > vt:
        return False
    return True


def _render_graph_context_document(shape: dict[str, Any]) -> str:
    """Render the workspace shape into a compact text document.

    Output format is a human + LLM readable summary:

    ::

        Workspace graph (ground truth from the structured graph store):
        Total entities: 117
        Total relationships: 67
        Entity types:
          - Process (count=48): Hydraulic Fracturing, Refining, ... (showing first 25 of 48)
          - Location (count=6): Asia-Pacific, Australia, Canada, Japan, Middle East, North America
        Relationship types:
          - RELATES_TO (count=48)
          - CITES (count=7)

    Returns an empty string when the workspace has zero entities so the
    caller can skip the document entirely.
    """
    entity_total = int(shape.get("entity_total") or 0)
    edge_total = int(shape.get("edge_total") or 0)
    if entity_total <= 0:
        return ""

    lines: list[str] = []
    lines.append(
        "Workspace graph (ground truth from the structured graph store):"
    )
    lines.append(f"Total entities: {entity_total}")
    lines.append(f"Total relationships: {edge_total}")
    lines.append("Entity types:")
    for et in shape.get("entity_types") or []:
        name = str(et.get("name") or "Unknown")
        count = int(et.get("count") or 0)
        examples = [str(x) for x in (et.get("top_examples") or []) if x]
        truncated = bool(et.get("truncated_examples"))
        examples_str = ", ".join(examples) if examples else "(no named examples)"
        if truncated:
            shown = len(examples)
            lines.append(
                f"  - {name} (count={count}): {examples_str} "
                f"(showing first {shown} of {count})"
            )
        else:
            lines.append(f"  - {name} (count={count}): {examples_str}")
    edge_types = shape.get("edge_types") or []
    if edge_types:
        lines.append("Relationship types:")
        for et in edge_types:
            name = str(et.get("name") or "Unknown")
            count = int(et.get("count") or 0)
            lines.append(f"  - {name} (count={count})")
    lines.append(
        "When the user asks 'how many', 'list all', or otherwise asks "
        "about aggregates by type, treat the counts and example names "
        "above as authoritative. Use the fact snippets that follow only "
        "as supporting context."
    )
    return "\n".join(lines)
