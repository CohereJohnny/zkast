"""Arq worker: PDF parse -> episodes."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import fitz  # PyMuPDF
import structlog
from arq.connections import RedisSettings

from app.chunking import chunk_page_text
from app.config import get_settings
from app.documents_repo import (
    delete_episodes_for_document,
    fetch_document,
    merge_run_completion_stats,
    merge_run_stats_warning,
    update_document,
    update_ingestion_run,
    insert_episodes,
)
from app.job_redis import job_hset, publish_job_event
from app.storage import LocalStorage
from app.workspace_repo import fetch_pipeline_settings

logger = structlog.get_logger(__name__)


async def worker_startup(ctx: dict[str, Any]) -> None:
    s = get_settings()
    ctx["database_url"] = s.database_url
    ctx["zkast_storage_root"] = s.zkast_storage_root


async def worker_shutdown(_ctx: dict[str, Any]) -> None:
    return


def _redis_settings_for_worker() -> RedisSettings:
    """Arq copies WorkerSettings.__dict__ directly (no descriptor protocol); keep a real RedisSettings here."""
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
                except Exception as exc:  # noqa: BLE001 — per-page isolation
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
                merge_run_completion_stats,
                database_url,
                run_id=ingestion_run_id,
                extra={"chunk_count": chunk_count, "page_count": page_count},
                status="succeeded",
            )
            await asyncio.to_thread(
                update_document,
                database_url,
                document_id=document_id,
                status="ready",
            )

            await publish_job_event(redis, job_id, "stage_completed", stage="parsing")
            await publish_job_event(redis, job_id, "job_completed", status="succeeded")
            await job_hset(
                redis,
                job_id,
                status="succeeded",
                progress=json.dumps({"percent": 100, "stage": "parsing"}),
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


class WorkerSettings:
    redis_settings = _redis_settings_for_worker()
    functions = [parse_document]
    on_startup = worker_startup
    on_shutdown = worker_shutdown
