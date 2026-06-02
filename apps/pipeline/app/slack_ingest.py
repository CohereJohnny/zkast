"""Background Slack channel import (arq worker job).

A busy channel can have thousands of threads; fetching each thread's replies
synchronously inside the HTTP request blocks for many minutes. This job runs
the fetch → segment → create-documents work in the worker with bounded
concurrency and streams progress to the job log, then enqueues the normal
``parse_document`` pipeline for each conversation unit.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from arq import create_pool
from arq.connections import RedisSettings

from app.config import get_settings
from app.documents_repo import (
    fetch_document_by_checksum,
    insert_document,
    insert_ingestion_run,
)
from app.job_redis import job_hset, publish_job_event, record_log
from app.secrets import decrypt
from app.slack_checksum import slack_unit_content_checksum, slack_unit_ingest_hash
from app.slack_client import (
    SlackApiError,
    SlackAuthError,
    SlackClient,
    build_user_name_map,
)
from app.slack_repo import (
    fetch_slack_oauth_secret_row,
    update_source_sync_state,
    upsert_slack_conversation_cache,
)
from app.slack_transcript import DEFAULT_SESSION_GAP_SECONDS, build_conversation_units
from app.storage import LocalStorage
from app.workspace_repo import fetch_pipeline_settings

logger = structlog.get_logger(__name__)

# Bound the worst case for very busy channels (also bounded by the date range).
MAX_ROOTS = 1000
REPLY_FETCH_CONCURRENCY = 5

_RANGE_DAYS: dict[str, int] = {
    "last_30_days": 30,
    "last_90_days": 90,
    "last_180_days": 180,
    "last_365_days": 365,
}


def compute_oldest_ts(
    *, range_key: str, cutoff_date: str | None, sync_cursor: str | None
) -> str | None:
    key = (range_key or "last_90_days").strip().lower()
    if key == "all":
        return None
    if key == "since_last":
        return sync_cursor or None
    if key == "custom" and cutoff_date:
        try:
            dt = datetime.fromisoformat(cutoff_date)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return f"{dt.timestamp():.6f}"
        except ValueError:
            return None
    days = _RANGE_DAYS.get(key, 90)
    return f"{time.time() - days * 86400:.6f}"


async def _pool(ctx: dict[str, Any]) -> Any:
    pool = ctx.get("arq_pool")
    if pool is not None:
        return pool
    s = get_settings()
    pool = await create_pool(RedisSettings.from_dsn(s.redis_url))
    ctx["arq_pool"] = pool
    return pool


async def import_slack_channel(
    ctx: dict[str, Any],
    *,
    workspace_id: str,
    source_id: str,
    channel_id: str,
    channel_name: str,
    range_key: str = "last_90_days",
    cutoff_date: str | None = None,
    history_limit: int = 1000,
    session_gap_seconds: int = DEFAULT_SESSION_GAP_SECONDS,
    segmentation_mode: str = "turn",
    sync_cursor: str | None = None,
    job_id: str,
) -> None:
    redis = ctx["redis"]
    database_url: str = ctx["database_url"]
    storage_root: str = ctx["zkast_storage_root"]
    settings = get_settings()

    async def _log(level: str, message: str, **data: Any) -> None:
        await record_log(
            redis,
            job_id=job_id,
            level=level,
            stage="slack_import",
            message=message,
            data=data or None,
        )

    async def _progress(percent: int, message: str) -> None:
        await job_hset(
            redis,
            job_id,
            status="running",
            progress=json.dumps({"percent": percent, "stage": "slack_import", "message": message}),
        )
        await publish_job_event(redis, job_id, "stage_progress", stage="slack_import", percent=percent)

    await job_hset(
        redis,
        job_id,
        status="running",
        workspace_id=workspace_id,
        kind="slack_import",
        progress=json.dumps({"percent": 0, "stage": "slack_import", "message": "starting"}),
    )
    await publish_job_event(redis, job_id, "stage_started", stage="slack_import")

    try:
        enc = fetch_slack_oauth_secret_row(database_url, workspace_id)
        if not enc:
            raise RuntimeError("Slack is not connected for this workspace")
        token = decrypt(settings.master_encryption_key_bytes, enc).decode("utf-8")
        client = SlackClient(bot_token=token)

        oldest = compute_oldest_ts(
            range_key=range_key, cutoff_date=cutoff_date, sync_cursor=sync_cursor
        )

        await _log("info", f"Fetching history for #{channel_name}", range=range_key)
        await _progress(5, "fetching channel history")
        roots = await client.channel_history(
            channel_id=channel_id, limit=min(history_limit, 1000), oldest=oldest
        )
        if len(roots) > MAX_ROOTS:
            await _log(
                "warning",
                f"Channel has {len(roots)} messages in range; importing the most recent {MAX_ROOTS}. "
                "Narrow the date range to include more older history in a separate import.",
            )
            roots = roots[:MAX_ROOTS]

        threaded = [
            m for m in roots if int(m.get("reply_count") or 0) > 0 and (m.get("thread_ts") or m.get("ts"))
        ]
        await _log(
            "info",
            f"Found {len(roots)} messages ({len(threaded)} threads). Fetching thread replies…",
            messages=len(roots),
            threads=len(threaded),
        )

        # Fetch thread replies with bounded concurrency + progress.
        replies_by_thread_ts: dict[str, list[dict[str, Any]]] = {}
        sem = asyncio.Semaphore(REPLY_FETCH_CONCURRENCY)
        done = 0
        total_threads = len(threaded)
        lock = asyncio.Lock()

        async def _one(ts: str) -> None:
            nonlocal done
            async with sem:
                try:
                    replies = await client.thread_replies(channel_id=channel_id, thread_ts=ts)
                    replies_by_thread_ts[ts] = replies
                except (SlackAuthError, SlackApiError) as exc:
                    logger.info("slack_thread_replies_skipped", thread_ts=ts, error=str(exc))
            async with lock:
                done += 1
                if total_threads and (done % 200 == 0 or done == total_threads):
                    pct = 5 + int(45 * done / total_threads)
                    await _progress(pct, f"fetched replies {done}/{total_threads}")
                    await _log("info", f"Fetched replies {done}/{total_threads}")

        await asyncio.gather(
            *[_one(str(m.get("thread_ts") or m.get("ts"))) for m in threaded]
        )

        await _progress(55, "resolving user names")
        user_names: dict[str, str] = {}
        try:
            user_names = build_user_name_map(await client.list_users())
        except (SlackAuthError, SlackApiError) as exc:
            await _log("warning", f"User-name resolution skipped: {exc}")

        await _progress(60, "segmenting conversations")
        units = build_conversation_units(
            channel_id=channel_id,
            channel_name=channel_name,
            root_messages=roots,
            replies_by_thread_ts=replies_by_thread_ts,
            user_names=user_names,
            session_gap_seconds=session_gap_seconds,
        )
        await _log("info", f"Segmented into {len(units)} conversation units")

        pipe = fetch_pipeline_settings(database_url, workspace_id)
        storage = LocalStorage(storage_root)
        pool = await _pool(ctx)

        created = 0
        skipped = 0
        all_ts: list[float] = []
        total_units = len(units) or 1
        for idx, unit in enumerate(units):
            transcript = unit["transcript"]
            for m in transcript.get("messages") or []:
                try:
                    all_ts.append(float(m.get("ts") or 0))
                except (TypeError, ValueError):
                    pass

            checksum = slack_unit_content_checksum(transcript)
            if fetch_document_by_checksum(database_url, workspace_id=workspace_id, checksum=checksum):
                skipped += 1
                continue

            external_conversation_id = unit["external_conversation_id"]
            upsert_slack_conversation_cache(
                database_url,
                workspace_id=workspace_id,
                source_id=source_id,
                external_conversation_id=external_conversation_id,
                payload=transcript,
            )

            doc_id = str(uuid.uuid4())
            run_id = str(uuid.uuid4())
            doc_job_id = str(uuid.uuid4())
            raw_bytes = json.dumps(transcript, ensure_ascii=False).encode("utf-8")
            storage_uri, _chk, byte_size = await storage.write_north_transcript_json(
                workspace_id, doc_id, raw_bytes, max_bytes=settings.max_upload_bytes
            )
            insert_document(
                database_url,
                document_id=doc_id,
                workspace_id=workspace_id,
                original_filename=f"slack-{external_conversation_id}.json",
                mime_type="application/json",
                byte_size=byte_size,
                storage_uri=storage_uri,
                checksum=checksum,
                replaces_document_id=None,
                status="queued",
                source_kind="slack_conversation",
                agent_id=source_id,
                external_conversation_id=external_conversation_id,
                source_metadata={
                    "channel_id": channel_id,
                    "channel_name": channel_name,
                    "unit_kind": unit["kind"],
                    "title": unit["title"],
                    "segmentation_mode": segmentation_mode,
                    "ingest_content_hash": slack_unit_ingest_hash(transcript),
                },
                raw_transcript_json=transcript,
            )
            insert_ingestion_run(
                database_url,
                run_id=run_id,
                document_id=doc_id,
                status="running",
                pipeline_version=settings.pipeline_version,
                llm_provider=str(pipe.get("default_llm_provider") or "cohere"),
                llm_model_small=str(pipe.get("small_model") or ""),
                llm_model_large=str(pipe.get("large_model") or ""),
                stats={"chunk_count": 0, "page_count": 0},
            )
            await job_hset(
                redis,
                doc_job_id,
                workspace_id=workspace_id,
                document_id=doc_id,
                ingestion_run_id=run_id,
                kind="document_parse",
                status="queued",
                progress='{"percent":0,"stage":"queued"}',
            )
            await pool.enqueue_job(
                "parse_document",
                workspace_id=workspace_id,
                document_id=doc_id,
                ingestion_run_id=run_id,
                job_id=doc_job_id,
                _job_id=f"{doc_job_id}:parse",
            )
            created += 1
            if created % 25 == 0 or idx == len(units) - 1:
                pct = 60 + int(35 * (idx + 1) / total_units)
                await _progress(pct, f"queued {created} documents")

        # Persist incremental sync coverage.
        newest_ts = max(all_ts) if all_ts else None
        oldest_ts = min(all_ts) if all_ts else None
        now_iso = datetime.now(tz=UTC).isoformat()

        def _iso(ts: float | None) -> str | None:
            return datetime.fromtimestamp(ts, tz=UTC).isoformat() if ts else None

        new_cursor = sync_cursor
        if newest_ts and (not new_cursor or float(newest_ts) > float(new_cursor)):
            new_cursor = f"{newest_ts:.6f}"
        update_source_sync_state(
            database_url,
            source_id=source_id,
            sync_cursor=new_cursor,
            provider_metadata_merge={
                "last_imported_at": now_iso,
                "last_import_range": range_key,
                "last_import_created": created,
                "last_import_skipped": skipped,
                "newest_message_ts": f"{newest_ts:.6f}" if newest_ts else None,
                "newest_message_at": _iso(newest_ts),
                "oldest_message_ts": f"{oldest_ts:.6f}" if oldest_ts else None,
                "oldest_message_at": _iso(oldest_ts),
            },
        )

        await job_hset(
            redis,
            job_id,
            status="succeeded",
            progress=json.dumps({"percent": 100, "stage": "slack_import", "message": "done"}),
        )
        await _log(
            "info",
            f"Import complete: {created} new conversation(s) queued, {skipped} already present.",
            created=created,
            skipped=skipped,
            units=len(units),
        )
        await publish_job_event(
            redis, job_id, "job_completed", stage="slack_import", created=created, skipped=skipped
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("slack_import_failed", source_id=source_id)
        await job_hset(
            redis,
            job_id,
            status="failed",
            progress=json.dumps({"percent": 0, "stage": "slack_import", "message": "failed"}),
        )
        await record_log(
            redis,
            job_id=job_id,
            level="error",
            stage="slack_import",
            message=f"Slack import failed: {exc}",
        )
        await publish_job_event(redis, job_id, "job_failed", stage="slack_import", reason=str(exc))
        raise
