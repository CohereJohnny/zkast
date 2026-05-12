"""Arq worker: PDF parse -> atomic notes -> graph extraction."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timezone
from typing import Any
from uuid import uuid4

import fitz  # PyMuPDF
import structlog
from arq import create_pool
from arq.connections import RedisSettings
from graphiti_core.nodes import EpisodeType

from app.chunking import chunk_page_text
from app.config import get_settings
from app.documents_repo import (
    delete_episodes_for_document,
    fetch_document,
    finalize_ingestion_run_success,
    list_episodes_for_ingestion_run,
    merge_run_stats_incremental,
    merge_run_stats_warning,
    update_document,
    update_ingestion_run,
    insert_episodes,
)
from app.entities_repo import upsert_entity_from_graphiti
from app.graphiti_factory import graphiti_for_workspace, resolve_cohere_api_key
from app.job_redis import job_hset, publish_job_event
from app.notes_llm import generate_notes_from_episodes
from app.notes_repo import (
    add_note_link,
    fetch_note,
    insert_note,
    list_note_ids_for_document,
)
from app.relationships_repo import insert_relationship_from_graphiti
from app.storage import LocalStorage
from app.workspace_repo import fetch_pipeline_settings
from app import entities_repo

logger = structlog.get_logger(__name__)


async def worker_startup(ctx: dict[str, Any]) -> None:
    s = get_settings()
    ctx["database_url"] = s.database_url
    ctx["zkast_storage_root"] = s.zkast_storage_root
    ctx["arq_pool"] = await create_pool(_redis_settings_for_worker())


async def worker_shutdown(ctx: dict[str, Any]) -> None:
    pool = ctx.get("arq_pool")
    if pool is not None:
        await pool.close()


def _redis_settings_for_worker() -> RedisSettings:
    url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    return RedisSettings.from_dsn(url)


async def parse_document(
    ctx: dict[str, Any],
    *,
    workspace_id: str,
    document_id: str,
    ingestion_run_id: str,
    job_id: str,
) -> None:
    redis = ctx["redis"]
    database_url: str = ctx["database_url"]
    storage_root: str = ctx["zkast_storage_root"]

    await job_hset(
        redis,
        job_id,
        status="running",
        workspace_id=workspace_id,
        document_id=document_id,
        ingestion_run_id=ingestion_run_id,
        kind="document_parse",
        progress=json.dumps({"percent": 0, "stage": "parsing"}),
    )
    await publish_job_event(redis, job_id, "stage_started", stage="parsing")

    try:
        await asyncio.to_thread(
            update_document,
            database_url,
            document_id=document_id,
            status="parsing",
        )

        doc = await asyncio.to_thread(
            fetch_document,
            database_url,
            workspace_id=workspace_id,
            document_id=document_id,
        )
        if not doc:
            raise RuntimeError("document not found")

        pipe = await asyncio.to_thread(fetch_pipeline_settings, database_url, workspace_id)
        chunk_tokens = int(pipe.get("chunk_size") or 512)
        max_chars = max(256, chunk_tokens * 4)

        path = LocalStorage.absolute_path_from_uri(doc["storage_uri"], storage_root)
        if not os.path.isfile(path):
            raise RuntimeError(
                f"PDF missing at {path}. Pipeline and worker must use the same "
                f"ZKAST_STORAGE_ROOT (Compose: shared pipeline_storage volume). "
                f"Re-upload if the DB row survived a volume reset."
            )

        def _open_doc() -> fitz.Document:
            return fitz.open(path)

        pdf = await asyncio.to_thread(_open_doc)
        try:
            page_count = pdf.page_count
            await asyncio.to_thread(
                update_document,
                database_url,
                document_id=document_id,
                page_count=page_count,
            )

            await asyncio.to_thread(delete_episodes_for_document, database_url, document_id=document_id)

            episode_rows: list[tuple[str, str, int, int, int]] = []
            sequence = 0
            throttle = max(1, page_count // 20) if page_count else 1

            for i in range(page_count):
                page_num = i + 1
                try:

                    def _page_text(idx: int = i) -> str:
                        return pdf.load_page(idx).get_text()

                    text = await asyncio.to_thread(_page_text)
                    for chunk_text, ps, pe in chunk_page_text(page_num, text, max_chars):
                        episode_rows.append((str(uuid4()), chunk_text, ps, pe, sequence))
                        sequence += 1
                except Exception as exc:  # noqa: BLE001
                    msg = f"page {page_num}: {exc}"
                    logger.warning("page_parse_warning", document_id=document_id, error=str(exc))
                    await asyncio.to_thread(
                        merge_run_stats_warning,
                        database_url,
                        run_id=ingestion_run_id,
                        warning=msg[:500],
                    )
                    await publish_job_event(
                        redis,
                        job_id,
                        "warning",
                        stage="parsing",
                        message=msg[:500],
                        page=page_num,
                    )

                if page_num % throttle == 0 or page_num == page_count:
                    pct = int(100 * page_num / page_count) if page_count else 100
                    prog = {"percent": pct, "stage": "parsing", "page": page_num, "total_pages": page_count}
                    await job_hset(redis, job_id, progress=json.dumps(prog))
                    await publish_job_event(
                        redis,
                        job_id,
                        "stage_progress",
                        stage="parsing",
                        current=page_num,
                        total=page_count,
                        percent=pct,
                    )

            if episode_rows:
                await asyncio.to_thread(
                    insert_episodes,
                    database_url,
                    workspace_id=workspace_id,
                    document_id=document_id,
                    ingestion_run_id=ingestion_run_id,
                    rows=episode_rows,
                )

            chunk_count = len(episode_rows)
            await asyncio.to_thread(
                merge_run_stats_incremental,
                database_url,
                run_id=ingestion_run_id,
                extra={"chunk_count": chunk_count, "page_count": page_count, "stage": "parsing_done"},
            )

            await publish_job_event(redis, job_id, "stage_completed", stage="parsing")

            pool = ctx["arq_pool"]
            await pool.enqueue_job(
                "generate_atomic_notes",
                workspace_id=workspace_id,
                document_id=document_id,
                ingestion_run_id=ingestion_run_id,
                job_id=job_id,
                _job_id=job_id,
            )
            await asyncio.to_thread(
                update_document,
                database_url,
                document_id=document_id,
                status="generating_notes",
            )

            await job_hset(
                redis,
                job_id,
                progress=json.dumps({"percent": 100, "stage": "parsing", "message": "queued_notes"}),
            )
        finally:
            await asyncio.to_thread(pdf.close)

    except Exception as exc:  # noqa: BLE001
        logger.exception("parse_document_failed", document_id=document_id, job_id=job_id)
        reason = str(exc)[:500]
        await asyncio.to_thread(
            update_document,
            database_url,
            document_id=document_id,
            status="failed",
            failure_reason=reason,
        )
        await asyncio.to_thread(
            update_ingestion_run,
            database_url,
            run_id=ingestion_run_id,
            status="failed",
            ended_at=datetime.now(UTC),
        )
        await publish_job_event(redis, job_id, "job_failed", reason=reason, stage="parsing")
        await job_hset(
            redis,
            job_id,
            status="failed",
            progress=json.dumps({"percent": 0, "stage": "parsing", "error": reason}),
        )


async def generate_atomic_notes(
    ctx: dict[str, Any],
    *,
    workspace_id: str,
    document_id: str,
    ingestion_run_id: str,
    job_id: str,
    episode_ids: list[str] | None = None,
) -> None:
    redis = ctx["redis"]
    database_url: str = ctx["database_url"]
    settings = get_settings()

    await job_hset(
        redis,
        job_id,
        progress=json.dumps({"percent": 0, "stage": "generating_notes"}),
    )
    await publish_job_event(redis, job_id, "stage_started", stage="generating_notes")

    try:
        episodes = await asyncio.to_thread(
            list_episodes_for_ingestion_run,
            database_url,
            ingestion_run_id=ingestion_run_id,
        )
        if episode_ids:
            allow = set(episode_ids)
            episodes = [e for e in episodes if e.get("id") in allow]
        if not episodes:
            raise RuntimeError("No episodes to generate notes from (check episode_ids filter)")
        pipe = await asyncio.to_thread(fetch_pipeline_settings, database_url, workspace_id)
        max_notes = min(500, max(1, int(pipe.get("max_notes_per_document") or 50)))
        model = str(pipe.get("large_model") or "command-a-plus-05-2026")

        api_key = resolve_cohere_api_key(settings, workspace_id)
        if not api_key:
            raise RuntimeError("No Cohere API key for note generation")

        note_payloads: list[dict[str, Any]] = []
        suggested_links: list[dict[str, Any]] = []
        if episodes:
            note_payloads, suggested_links = await generate_notes_from_episodes(
                api_key=api_key,
                model=model,
                episodes=episodes,
                max_notes=max_notes,
            )

        created_ids: list[str] = []
        for payload in note_payloads:
            nid = str(uuid4())
            await asyncio.to_thread(
                insert_note,
                database_url,
                note_id=nid,
                workspace_id=workspace_id,
                title=payload["title"],
                body=payload["body"],
                tags=payload.get("tags") or [],
                origin="generated",
                created_by_user_id=None,
                episode_ids=payload["source_episode_ids"],
                is_user_edited=False,
            )
            created_ids.append(nid)

        for ln in suggested_links:
            fr = ln["from"]
            to = ln["to"]
            if 0 <= fr < len(created_ids) and 0 <= to < len(created_ids):
                try:
                    await asyncio.to_thread(
                        add_note_link,
                        database_url,
                        workspace_id=workspace_id,
                        source_note_id=created_ids[fr],
                        target_note_id=created_ids[to],
                        kind=ln.get("kind", "related"),
                        custom_label=None,
                        origin="generated",
                    )
                except Exception as link_exc:  # noqa: BLE001
                    logger.warning("note_link_skip", error=str(link_exc))

        await asyncio.to_thread(
            merge_run_stats_incremental,
            database_url,
            run_id=ingestion_run_id,
            extra={"note_count": len(created_ids), "stage": "notes_done"},
        )

        pool = ctx["arq_pool"]
        await pool.enqueue_job(
            "extract_graph",
            workspace_id=workspace_id,
            document_id=document_id,
            ingestion_run_id=ingestion_run_id,
            job_id=job_id,
            _job_id=job_id,
        )
        await asyncio.to_thread(
            update_document,
            database_url,
            document_id=document_id,
            status="extracting_graph",
        )

        await publish_job_event(redis, job_id, "stage_completed", stage="generating_notes")
        await job_hset(
            redis,
            job_id,
            progress=json.dumps({"percent": 50, "stage": "extracting_graph"}),
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("generate_atomic_notes_failed", document_id=document_id)
        reason = str(exc)[:500]
        await asyncio.to_thread(
            update_document,
            database_url,
            document_id=document_id,
            status="failed",
            failure_reason=reason,
        )
        await asyncio.to_thread(
            update_ingestion_run,
            database_url,
            run_id=ingestion_run_id,
            status="failed",
            ended_at=datetime.now(UTC),
        )
        await publish_job_event(redis, job_id, "job_failed", reason=reason, stage="generating_notes")
        await job_hset(
            redis,
            job_id,
            status="failed",
            progress=json.dumps({"percent": 0, "stage": "generating_notes", "error": reason}),
        )


async def extract_graph(
    ctx: dict[str, Any],
    *,
    workspace_id: str,
    document_id: str,
    ingestion_run_id: str,
    job_id: str,
) -> None:
    redis = ctx["redis"]
    database_url: str = ctx["database_url"]
    settings = get_settings()

    await publish_job_event(redis, job_id, "stage_started", stage="extracting_graph")
    await asyncio.to_thread(
        update_document,
        database_url,
        document_id=document_id,
        status="building_graph",
    )

    ref = datetime.now(timezone.utc)
    entity_count = 0
    edge_count = 0

    try:
        graphiti = await graphiti_for_workspace(settings, workspace_id)
        episodes = await asyncio.to_thread(
            list_episodes_for_ingestion_run,
            database_url,
            ingestion_run_id=ingestion_run_id,
        )

        for ep in episodes:
            body = (ep.get("text") or "")[:50000]
            if not body.strip():
                continue
            res = await graphiti.add_episode(
                name=f"pdf-chunk-{ep.get('sequence')}",
                episode_body=body,
                source_description=f"PDF pages {ep.get('page_start')}-{ep.get('page_end')}",
                reference_time=ref,
                source=EpisodeType.text,
                group_id=workspace_id,
            )
            ep_id = str(ep["id"])
            for node in res.nodes:
                await asyncio.to_thread(
                    upsert_entity_from_graphiti,
                    database_url,
                    workspace_id=workspace_id,
                    graphiti_uuid=node.uuid,
                    name=node.name,
                    labels=list(node.labels or []),
                    summary=node.summary or "",
                    attributes=dict(node.attributes or {}),
                    episode_id=ep_id,
                    note_id=None,
                )
                entity_count += 1
            for edge in res.edges:
                src = await asyncio.to_thread(
                    entities_repo.fetch_entity_id_for_graphiti_uuid,
                    database_url,
                    edge.source_node_uuid,
                )
                tgt = await asyncio.to_thread(
                    entities_repo.fetch_entity_id_for_graphiti_uuid,
                    database_url,
                    edge.target_node_uuid,
                )
                if not src or not tgt:
                    continue
                await asyncio.to_thread(
                    insert_relationship_from_graphiti,
                    database_url,
                    workspace_id=workspace_id,
                    graphiti_edge_uuid=edge.uuid,
                    source_entity_id=src,
                    target_entity_id=tgt,
                    rel_type=edge.name,
                    fact=edge.fact,
                    confidence=1.0,
                    valid_from=edge.valid_at,
                    valid_to=edge.invalid_at,
                    episode_id=ep_id,
                    note_id=None,
                )
                edge_count += 1

        note_ids = await asyncio.to_thread(
            list_note_ids_for_document,
            database_url,
            workspace_id=workspace_id,
            document_id=document_id,
        )
        for nid in note_ids:
            note_row = await asyncio.to_thread(
                fetch_note,
                database_url,
                workspace_id=workspace_id,
                note_id=nid,
            )
            if not note_row:
                continue
            body = f"# {note_row['title']}\n\n{note_row['body']}"[:50000]
            res = await graphiti.add_episode(
                name=f"note-{nid[:8]}",
                episode_body=body,
                source_description="Atomic note",
                reference_time=ref,
                source=EpisodeType.text,
                group_id=workspace_id,
            )
            for node in res.nodes:
                await asyncio.to_thread(
                    upsert_entity_from_graphiti,
                    database_url,
                    workspace_id=workspace_id,
                    graphiti_uuid=node.uuid,
                    name=node.name,
                    labels=list(node.labels or []),
                    summary=node.summary or "",
                    attributes=dict(node.attributes or {}),
                    episode_id=None,
                    note_id=nid,
                )
                entity_count += 1
            for edge in res.edges:
                src = await asyncio.to_thread(
                    entities_repo.fetch_entity_id_for_graphiti_uuid,
                    database_url,
                    edge.source_node_uuid,
                )
                tgt = await asyncio.to_thread(
                    entities_repo.fetch_entity_id_for_graphiti_uuid,
                    database_url,
                    edge.target_node_uuid,
                )
                if not src or not tgt:
                    continue
                await asyncio.to_thread(
                    insert_relationship_from_graphiti,
                    database_url,
                    workspace_id=workspace_id,
                    graphiti_edge_uuid=edge.uuid,
                    source_entity_id=src,
                    target_entity_id=tgt,
                    rel_type=edge.name,
                    fact=edge.fact,
                    confidence=1.0,
                    valid_from=edge.valid_at,
                    valid_to=edge.invalid_at,
                    episode_id=None,
                    note_id=nid,
                )
                edge_count += 1

        await asyncio.to_thread(
            merge_run_stats_incremental,
            database_url,
            run_id=ingestion_run_id,
            extra={
                "graph_entity_extractions": entity_count,
                "graph_edge_extractions": edge_count,
                "stage": "graph_done",
            },
        )
        await asyncio.to_thread(
            finalize_ingestion_run_success,
            database_url,
            run_id=ingestion_run_id,
            extra={"graph_entity_extractions": entity_count, "graph_edge_extractions": edge_count},
        )
        await asyncio.to_thread(
            update_document,
            database_url,
            document_id=document_id,
            status="ready",
            clear_failure_reason=True,
        )

        await publish_job_event(redis, job_id, "stage_completed", stage="building_graph")
        await publish_job_event(redis, job_id, "job_completed", status="succeeded")
        await job_hset(
            redis,
            job_id,
            status="succeeded",
            progress=json.dumps({"percent": 100, "stage": "ready"}),
        )

    except Exception as exc:  # noqa: BLE001
        logger.exception("extract_graph_failed", document_id=document_id)
        reason = str(exc)[:500]
        await asyncio.to_thread(
            update_document,
            database_url,
            document_id=document_id,
            status="failed",
            failure_reason=reason,
        )
        await asyncio.to_thread(
            update_ingestion_run,
            database_url,
            run_id=ingestion_run_id,
            status="failed",
            ended_at=datetime.now(UTC),
        )
        await publish_job_event(redis, job_id, "job_failed", reason=reason, stage="extracting_graph")
        await job_hset(
            redis,
            job_id,
            status="failed",
            progress=json.dumps({"percent": 0, "stage": "extracting_graph", "error": reason}),
        )


class WorkerSettings:
    redis_settings = _redis_settings_for_worker()
    functions = [parse_document, generate_atomic_notes, extract_graph]
    on_startup = worker_startup
    on_shutdown = worker_shutdown
