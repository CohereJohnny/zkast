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
        await publish_job_event(
            redis, turn_id, "retrieval_started", query_text=query_text[:1000]
        )

        retrieved_items, documents, total_candidates, truncated = await _retrieve(
            settings,
            database_url,
            workspace_id=workspace_id,
            query_text=query_text,
            scope=dict(session.get("scope") or {}),
            top_k=top_k,
            doc_token_budget=doc_token_budget,
        )

        await record_log(
            redis,
            job_id=turn_id,
            level="info" if documents else "warning",
            stage="chat_turn",
            message=(
                f"retrieval: graphiti returned {total_candidates} hit(s); "
                f"{len(documents)} document(s) kept after scope filters"
            ),
            data={
                "total_candidates": total_candidates,
                "kept": len(documents),
                "truncated": truncated,
            },
            database_url=None,
            ingestion_run_id=None,
        )

        # ---- Persist RetrievalRecord BEFORE the LLM call (FR-41) ----
        retrieval_strategy = "graphiti_hybrid_v1"
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
        await asyncio.to_thread(
            update_assistant_message,
            database_url,
            message_id=assistant_message_id,
            content=final_text,
            status="complete",
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
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
) -> tuple[list[dict[str, Any]], list[ChatDocument], int, bool]:
    """Run Graphiti hybrid search + apply Postgres-side scope filters.

    Returns ``(retrieved_items, documents, total_candidates, truncated)``:

    - ``retrieved_items``: JSON-serializable list for the
      ``retrieval_records.retrieved_items`` column. One entry per hit with
      ``kind``, ``id``, ``score``, ``excerpt``.
    - ``documents``: the same hits rendered as ``ChatDocument`` objects to
      pass to Cohere.
    - ``total_candidates``: Graphiti's pre-truncation count.
    - ``truncated``: True when more candidates existed than ``top_k``.
    """
    if not query_text.strip():
        return [], [], 0, False

    # ---- Graphiti hybrid search ----
    try:
        graphiti = await graphiti_for_workspace(settings, workspace_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "chat_retrieval_graphiti_unavailable",
            workspace_id=workspace_id,
            error=str(exc),
        )
        return [], [], 0, False

    try:
        edges = await graphiti.search(
            query=query_text, group_ids=[workspace_id], num_results=top_k
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("chat_retrieval_graphiti_search_failed", error=str(exc))
        return [], [], 0, False

    edges = list(edges or [])
    total_candidates = len(edges)
    truncated = total_candidates > top_k
    if truncated:
        edges = edges[:top_k]

    # ---- Apply scope filters + build documents ----
    allowed_entity_types = set(_str_list(scope.get("entity_types")))
    allowed_edge_types = set(_str_list(scope.get("edge_types")))
    allowed_document_ids = set(_str_list(scope.get("document_ids")))
    allowed_tags = set(_str_list(scope.get("tags")))
    valid_at = _parse_iso(scope.get("valid_at"))
    seed_entity_ids = set(_str_list(scope.get("seed_entity_ids")))

    retrieved_items: list[dict[str, Any]] = []
    documents: list[ChatDocument] = []
    budget_chars = doc_token_budget * APPROX_CHARS_PER_TOKEN
    used_chars = 0

    # Edges are ordered by Graphiti's relevance; iterate smallest-first by
    # excerpt length to maximize the count we can fit inside the budget.
    candidate_rows: list[tuple[int, dict[str, Any]]] = []
    for edge in edges:
        fact = str(_attr(edge, "fact", "") or "").strip()
        if not fact:
            continue
        edge_type = str(_attr(edge, "name", "") or "RELATES_TO")
        if allowed_edge_types and edge_type not in allowed_edge_types:
            continue

        # Optional temporal filter: drop edges whose validity window doesn't
        # include valid_at.
        if valid_at is not None:
            edge_valid_from = _attr(edge, "valid_at")
            edge_valid_to = _attr(edge, "invalid_at")
            if not _temporally_overlaps(valid_at, edge_valid_from, edge_valid_to):
                continue

        edge_uuid = str(_attr(edge, "uuid", "") or "")
        rel_id_prefix = f"relationship:{edge_uuid}" if edge_uuid else None
        excerpt = fact[:1000]
        if not rel_id_prefix:
            continue

        candidate_rows.append(
            (
                len(excerpt),
                {
                    "kind": "relationship",
                    "id": edge_uuid,
                    "type": edge_type,
                    "score": float(_attr(edge, "score", 0.0) or 0.0),
                    "excerpt": excerpt,
                    "source_node_uuid": str(
                        _attr(edge, "source_node_uuid", "") or ""
                    ),
                    "target_node_uuid": str(
                        _attr(edge, "target_node_uuid", "") or ""
                    ),
                    "doc_id": rel_id_prefix,
                },
            )
        )

    # Smallest-first ordering preserves Graphiti's relevance for the top
    # K and lets us pack more documents into the budget.
    candidate_rows.sort(key=lambda t: t[0])

    # ---- Optional Postgres-side filters (document / tag / type / seed) ----
    if (
        allowed_document_ids
        or allowed_tags
        or allowed_entity_types
        or seed_entity_ids
    ):
        # Resolve the source / target entity ids for each candidate.
        from app import entities_repo  # local import — avoids cycles in tests

        for size, row in candidate_rows:
            src_ent = await asyncio.to_thread(
                entities_repo.fetch_entity_id_for_graphiti_uuid,
                database_url,
                row["source_node_uuid"],
            )
            tgt_ent = await asyncio.to_thread(
                entities_repo.fetch_entity_id_for_graphiti_uuid,
                database_url,
                row["target_node_uuid"],
            )
            row["source_entity_id"] = src_ent
            row["target_entity_id"] = tgt_ent

            if seed_entity_ids:
                if (
                    src_ent not in seed_entity_ids
                    and tgt_ent not in seed_entity_ids
                ):
                    row["_skip"] = True
                    continue

            if allowed_entity_types or allowed_document_ids or allowed_tags:
                ok = await asyncio.to_thread(
                    _scope_check_for_entities,
                    database_url,
                    workspace_id=workspace_id,
                    entity_ids=[e for e in (src_ent, tgt_ent) if e],
                    allowed_entity_types=allowed_entity_types,
                    allowed_document_ids=allowed_document_ids,
                    allowed_tags=allowed_tags,
                )
                if not ok:
                    row["_skip"] = True

    # ---- Pack into budget ----
    for _size, row in candidate_rows:
        if row.get("_skip"):
            continue
        excerpt = row["excerpt"]
        if used_chars + len(excerpt) > budget_chars and documents:
            break
        used_chars += len(excerpt)
        retrieved_items.append(
            {
                "kind": row["kind"],
                "id": row["id"],
                "type": row.get("type"),
                "score": row.get("score"),
                "excerpt": excerpt,
                "source_entity_id": row.get("source_entity_id"),
                "target_entity_id": row.get("target_entity_id"),
            }
        )
        documents.append(
            ChatDocument(
                id=row["doc_id"],
                text=excerpt,
                title=row.get("type"),
                metadata={
                    "kind": row["kind"],
                    "score": str(row.get("score") or 0.0),
                },
            )
        )

    return retrieved_items, documents, total_candidates, truncated


def _scope_check_for_entities(
    database_url: str,
    *,
    workspace_id: str,
    entity_ids: list[str],
    allowed_entity_types: set[str],
    allowed_document_ids: set[str],
    allowed_tags: set[str],
) -> bool:
    """Return True when at least one of the entity_ids passes every active
    filter. Tags filter via the entity's source notes.
    """
    if not entity_ids:
        return False
    import psycopg

    with psycopg.connect(database_url) as conn:
        for eid in entity_ids:
            row = conn.execute(
                "SELECT type FROM entities WHERE id = %s::uuid LIMIT 1",
                (eid,),
            ).fetchone()
            if row is None:
                continue
            etype = row[0]
            if allowed_entity_types and etype not in allowed_entity_types:
                continue
            if allowed_document_ids:
                hit = conn.execute(
                    """
                    SELECT 1
                    FROM entity_episodes ee
                    JOIN episodes e ON e.id = ee.episode_id
                    WHERE ee.entity_id = %s::uuid
                      AND e.document_id = ANY(%s::uuid[])
                    LIMIT 1
                    """,
                    (eid, list(allowed_document_ids)),
                ).fetchone()
                if hit is None:
                    continue
            if allowed_tags:
                hit = conn.execute(
                    """
                    SELECT 1
                    FROM entity_notes en
                    JOIN atomic_notes n ON n.id = en.note_id
                    WHERE en.entity_id = %s::uuid
                      AND n.tags && %s::text[]
                    LIMIT 1
                    """,
                    (eid, list(allowed_tags)),
                ).fetchone()
                if hit is None:
                    continue
            return True
    return False


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
