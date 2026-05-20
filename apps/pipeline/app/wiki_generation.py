"""LLM Wiki generation worker.

Compiles atomic notes for a workspace (or a North-agent scope) into a
collection of human-readable wiki pages: an index, a changelog, per-tag
topic pages, per-entity summary pages, a workspace synthesis page, and one
source-summary page per contributing document or conversation.

The MVP shipped in Sprint E uses **deterministic, source-grounded synthesis**:
pages are built by clustering existing notes/tags/entities and assembling
their bodies into Markdown. This keeps the audit trail tight (no
hallucinated content), satisfies the OpenSpec immutability requirements,
and is cheap enough to run frequently.

LLM-driven page bodies can be plugged in later by replacing the
``_compose_*`` helpers; the data model, telemetry contract, and citation
rows do not need to change.

See ``specs/openspecs/llm-wiki-memory.md`` for the requirements authority.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import structlog

from app.job_redis import (
    job_hset,
    publish_job_event,
    record_log,
    record_metric,
)
from app.wiki_repo import (
    fetch_notes_for_wiki,
    fetch_wiki_space,
    insert_wiki_job,
    insert_wiki_mutation,
    list_wiki_pages,
    replace_wiki_page_sources,
    slugify,
    update_wiki_job_status,
    update_wiki_space_status,
    upsert_wiki_page,
)


logger = structlog.get_logger(__name__)

STAGE = "wiki_generation"

WIKI_JOB_STATUS_QUEUED = "queued"
WIKI_JOB_STATUS_RUNNING = "running"
WIKI_JOB_STATUS_SUCCEEDED = "succeeded"
WIKI_JOB_STATUS_FAILED = "failed"


# ---------------------------------------------------------------------------
# Telemetry helpers
# ---------------------------------------------------------------------------


async def _log(
    redis: Any | None,
    *,
    job_id: str,
    message: str,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    if not redis:
        return
    await record_log(
        redis,
        job_id=job_id,
        level=level,
        stage=STAGE,
        message=message,
        data=data,
    )


async def _progress(
    redis: Any | None,
    *,
    job_id: str,
    percent: int,
    current: int,
    total: int,
    stats: dict[str, Any],
) -> None:
    if not redis:
        return
    pct = max(0, min(100, percent))
    prog = {
        "percent": pct,
        "stage": STAGE,
        "current": current,
        "total": total,
        "pages_created": stats.get("pages_created", 0),
        "pages_updated": stats.get("pages_updated", 0),
        "citations_added": stats.get("citations_added", 0),
    }
    await job_hset(redis, job_id, progress=json.dumps(prog))
    await publish_job_event(
        redis,
        job_id,
        "stage_progress",
        stage=STAGE,
        current=current,
        total=total,
        percent=pct,
    )


async def _running(
    redis: Any | None,
    *,
    job_id: str,
    workspace_id: str,
    wiki_space_id: str,
) -> None:
    if not redis:
        return
    await job_hset(
        redis,
        job_id,
        workspace_id=workspace_id,
        wiki_space_id=wiki_space_id,
        kind="wiki_generation",
        status="running",
        progress=json.dumps({"percent": 5, "stage": STAGE}),
    )
    await publish_job_event(redis, job_id, "stage_started", stage=STAGE)
    await _log(
        redis,
        job_id=job_id,
        message="Wiki generation started",
        data={"wiki_space_id": wiki_space_id},
    )


async def _finish(
    redis: Any | None,
    *,
    job_id: str,
    status: str,
    stats: dict[str, Any],
    failure_reason: str | None = None,
) -> None:
    if not redis:
        return
    pct = 100 if status == WIKI_JOB_STATUS_SUCCEEDED else 0
    await job_hset(
        redis,
        job_id,
        status=status,
        progress=json.dumps({"percent": pct, "stage": STAGE, "stats": stats}),
        failure_reason=failure_reason,
    )
    if status == WIKI_JOB_STATUS_FAILED:
        await publish_job_event(
            redis,
            job_id,
            "job_failed",
            reason=failure_reason or "wiki_generation_failed",
            stage=STAGE,
        )
        await _log(
            redis,
            job_id=job_id,
            level="error",
            message=failure_reason or "Wiki generation failed",
        )
        return
    await publish_job_event(redis, job_id, "job_completed", stage=STAGE)
    await _log(
        redis,
        job_id=job_id,
        message=(
            f"Wiki generation complete — created {stats.get('pages_created', 0)}, "
            f"updated {stats.get('pages_updated', 0)}, "
            f"citations {stats.get('citations_added', 0)}, "
            f"links {stats.get('links_added', 0)}"
        ),
        data=stats,
    )


# ---------------------------------------------------------------------------
# Page composition helpers (deterministic synthesis)
# ---------------------------------------------------------------------------


def _truncate(text: str | None, limit: int = 600) -> str:
    if not text:
        return ""
    t = text.strip()
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "…"


def _format_tag(t: str) -> str:
    return t.replace("-", " ").strip().title() or "Untitled topic"


def _note_excerpt(note: dict[str, Any], limit: int = 300) -> str:
    body = str(note.get("body") or "").strip()
    return _truncate(body, limit)


def _compose_topic_page(
    *,
    tag: str,
    notes: list[dict[str, Any]],
) -> tuple[str, str, str]:
    """Returns (title, summary, body) for a tag-driven topic page."""
    title = f"Topic: {_format_tag(tag)}"
    summary = (
        f"Synthesis of {len(notes)} note(s) tagged `{tag}`. Auto-generated "
        f"from atomic notes; each claim links back to its source note."
    )
    lines: list[str] = [
        f"# {title}",
        "",
        f"_Auto-generated synthesis from {len(notes)} note(s) tagged `{tag}`._",
        "",
        "## Notes contributing to this topic",
        "",
    ]
    for n in notes:
        nid = n.get("id") or ""
        ntitle = (n.get("title") or "Untitled note").strip() or "Untitled note"
        excerpt = _note_excerpt(n, 280)
        lines.append(f"- **{ntitle}** — {excerpt}")
        lines.append(f"  ([note:{nid}](note://{nid}))")
    if any(n.get("memory_context") for n in notes):
        lines.extend(["", "## Memory context", ""])
        for n in notes:
            ctx = (n.get("memory_context") or "").strip()
            if not ctx:
                continue
            lines.append(f"- {ctx}  ([note:{n.get('id')}](note://{n.get('id')}))")
    lines.extend([
        "",
        "## Sources",
        "",
        "See the citation panel for the full source list.",
        "",
    ])
    return title, summary, "\n".join(lines)


def _compose_source_summary_page(
    *,
    bucket_key: str,
    bucket_label: str,
    notes: list[dict[str, Any]],
) -> tuple[str, str, str]:
    title = f"Source: {bucket_label}"
    summary = (
        f"Summary of {len(notes)} note(s) derived from {bucket_label}. "
        "Auto-generated; each bullet links back to its atomic note."
    )
    lines = [
        f"# {title}",
        "",
        f"_Source identifier: `{bucket_key}`._",
        "",
        "## Notes derived from this source",
        "",
    ]
    for n in notes:
        nid = n.get("id") or ""
        ntitle = (n.get("title") or "Untitled note").strip() or "Untitled note"
        excerpt = _note_excerpt(n, 220)
        lines.append(f"- **{ntitle}** — {excerpt} ([note:{nid}](note://{nid}))")
    return title, summary, "\n".join(lines)


def _compose_synthesis_page(
    *,
    scope_label: str,
    note_count: int,
    topic_counts: dict[str, int],
    source_counts: dict[str, int],
) -> tuple[str, str, str]:
    top_topics = sorted(topic_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    top_sources = sorted(source_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    title = "Workspace synthesis"
    summary = (
        f"High-level view of the {scope_label} memory: {note_count} note(s), "
        f"{len(topic_counts)} topic(s), {len(source_counts)} source(s)."
    )
    lines = [
        f"# {title}",
        "",
        summary,
        "",
        "## Top topics",
        "",
    ]
    for tag, n in top_topics:
        lines.append(f"- `{tag}` — {n} note(s)")
    if not top_topics:
        lines.append("_(no tags yet)_")
    lines.extend(["", "## Most-cited sources", ""])
    for src, n in top_sources:
        lines.append(f"- {src} — {n} note(s)")
    if not top_sources:
        lines.append("_(no sources yet)_")
    return title, summary, "\n".join(lines)


def _compose_index_page(*, pages: list[dict[str, Any]]) -> tuple[str, str, str]:
    title = "Wiki index"
    summary = f"Index of {len(pages)} wiki page(s)."
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in pages:
        by_type[str(p.get("page_type") or "other")].append(p)
    type_order = [
        "synthesis",
        "topic",
        "entity",
        "comparison",
        "source_summary",
        "changelog",
    ]
    lines = [f"# {title}", "", summary, ""]
    for pt in type_order:
        rows = by_type.get(pt)
        if not rows:
            continue
        lines.append(f"## {pt.replace('_', ' ').title()} ({len(rows)})")
        lines.append("")
        for p in rows:
            slug = p.get("slug")
            t = p.get("title") or slug
            lines.append(f"- [{t}](wiki://{slug})")
        lines.append("")
    return title, summary, "\n".join(lines)


def _compose_changelog_page(
    *,
    job_id: str,
    started_iso: str,
    stats: dict[str, Any],
    existing_body: str | None,
) -> tuple[str, str, str]:
    title = "Changelog"
    summary = "Append-only history of wiki generation runs."
    entry = (
        f"## [{started_iso}] generate · job `{job_id[:8]}…`\n"
        f"- notes_considered: {stats.get('notes_considered', 0)}\n"
        f"- pages_created: {stats.get('pages_created', 0)}\n"
        f"- pages_updated: {stats.get('pages_updated', 0)}\n"
        f"- citations_added: {stats.get('citations_added', 0)}\n"
        f"- links_added: {stats.get('links_added', 0)}\n"
    )
    if existing_body and existing_body.strip():
        # Append: keep new entry at the top so the most recent run is first.
        body = f"# {title}\n\n{entry}\n" + existing_body.split("# Changelog", 1)[-1].lstrip()
    else:
        body = f"# {title}\n\n{entry}"
    return title, summary, body


# ---------------------------------------------------------------------------
# Worker entry point
# ---------------------------------------------------------------------------


async def run_wiki_generation_job(
    ctx: dict[str, Any],
    *,
    workspace_id: str,
    wiki_space_id: str,
    job_id: str | None = None,
) -> None:
    """arq task: compile a wiki for one workspace or agent scope.

    Reads atomic notes (and A-MEM derived fields when present) and produces a
    deterministic set of synthesis, topic, source-summary, index, and
    changelog pages with citations back to the contributing notes.
    """
    database_url: str = ctx["database_url"]
    redis = ctx.get("redis")

    space = fetch_wiki_space(
        database_url, workspace_id=workspace_id, space_id=wiki_space_id
    )
    if not space:
        raise RuntimeError(f"Wiki space {wiki_space_id} not found in workspace {workspace_id}")

    agent_id = space.get("agent_id") if space.get("scope_kind") == "agent" else None
    scope_label = "agent" if agent_id else "workspace"

    job_id = job_id or insert_wiki_job(
        database_url,
        workspace_id=workspace_id,
        wiki_space_id=wiki_space_id,
        kind="generate",
    )

    stats: dict[str, Any] = {
        "notes_considered": 0,
        "pages_created": 0,
        "pages_updated": 0,
        "pages_skipped": 0,
        "pages_marked_stale": 0,
        "links_added": 0,
        "citations_added": 0,
        "contradictions_detected": 0,
        "llm_calls": 0,
    }
    started_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        update_wiki_space_status(database_url, space_id=wiki_space_id, status="generating")
        update_wiki_job_status(database_url, job_id=job_id, status=WIKI_JOB_STATUS_RUNNING)
        await _running(
            redis, job_id=job_id, workspace_id=workspace_id, wiki_space_id=wiki_space_id
        )

        notes = fetch_notes_for_wiki(
            database_url,
            workspace_id=workspace_id,
            agent_id=agent_id,
            limit=int((space.get("settings") or {}).get("max_notes") or 200),
        )
        stats["notes_considered"] = len(notes)

        await _log(
            redis,
            job_id=job_id,
            message=(
                f"Loaded {len(notes)} note(s) for {scope_label} wiki "
                f"(agent_id={agent_id or 'none'})"
            ),
            data={"notes": len(notes), "agent_id": agent_id},
        )

        if not notes:
            await _log(
                redis,
                job_id=job_id,
                level="warning",
                message="No notes available for this scope; nothing to generate.",
            )
            update_wiki_job_status(
                database_url,
                job_id=job_id,
                status=WIKI_JOB_STATUS_SUCCEEDED,
                stats={**stats, "message": "no_notes"},
            )
            update_wiki_space_status(
                database_url, space_id=wiki_space_id, status="empty", mark_generated=True
            )
            await _finish(
                redis,
                job_id=job_id,
                status=WIKI_JOB_STATUS_SUCCEEDED,
                stats={**stats, "message": "no_notes"},
            )
            return

        # ----- Cluster notes by topic (tag) and by source bucket -----
        by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for n in notes:
            tags = n.get("tags") or []
            if not tags:
                by_tag["uncategorised"].append(n)
            for t in tags:
                key = str(t).strip().lower()
                if not key:
                    continue
                by_tag[key].append(n)
            origin = (n.get("origin") or "manual").strip().lower()
            bucket = f"origin:{origin}"
            if n.get("agent_id"):
                bucket = f"agent:{n['agent_id']}"
            by_source[bucket].append(n)

        topic_count = len(by_tag)
        source_count = len(by_source)
        await _log(
            redis,
            job_id=job_id,
            message=(
                f"Identified {topic_count} topic cluster(s) and {source_count} source bucket(s)"
            ),
            data={"topics": topic_count, "sources": source_count},
        )

        await _progress(
            redis,
            job_id=job_id,
            percent=15,
            current=0,
            total=topic_count + source_count + 3,
            stats=stats,
        )

        produced: list[dict[str, Any]] = []
        candidate_total = topic_count + source_count + 3  # +synthesis +index +changelog
        current_index = 0

        # ----- Topic pages -----
        for tag, tnotes in sorted(by_tag.items(), key=lambda kv: kv[0]):
            current_index += 1
            slug = slugify(f"topic-{tag}", fallback="topic")
            title, summary, body = _compose_topic_page(tag=tag, notes=tnotes)
            page_id, action = upsert_wiki_page(
                database_url,
                wiki_space_id=wiki_space_id,
                slug=slug,
                title=title,
                page_type="topic",
                body=body,
                summary=summary,
                status="ready",
                metadata={"tag": tag, "note_count": len(tnotes)},
            )
            citations = [
                {"source_kind": "atomic_note", "source_id": str(n["id"]), "weight": 1.0}
                for n in tnotes
                if n.get("id")
            ]
            inserted = replace_wiki_page_sources(
                database_url, wiki_page_id=page_id, sources=citations
            )
            stats["citations_added"] += inserted
            stats["pages_created" if action == "created" else "pages_updated"] += 1
            insert_wiki_mutation(
                database_url,
                wiki_job_id=job_id,
                wiki_page_id=page_id,
                mutation_type=(
                    "page_created" if action == "created" else "page_updated"
                ),
                payload={"page_type": "topic", "tag": tag, "notes": len(tnotes)},
            )
            produced.append({"page_type": "topic", "slug": slug, "title": title})
            await _progress(
                redis,
                job_id=job_id,
                percent=15 + int(60 * current_index / max(candidate_total, 1)),
                current=current_index,
                total=candidate_total,
                stats=stats,
            )
            await _log(
                redis,
                job_id=job_id,
                message=f"{action} topic page “{title}” ({len(tnotes)} note(s))",
                data={"slug": slug, "tag": tag},
            )

        # ----- Source-summary pages -----
        for bucket_key, snotes in sorted(by_source.items(), key=lambda kv: kv[0]):
            current_index += 1
            label = bucket_key.split(":", 1)[-1]
            slug = slugify(f"source-{bucket_key}", fallback="source")
            title, summary, body = _compose_source_summary_page(
                bucket_key=bucket_key, bucket_label=label, notes=snotes
            )
            page_id, action = upsert_wiki_page(
                database_url,
                wiki_space_id=wiki_space_id,
                slug=slug,
                title=title,
                page_type="source_summary",
                body=body,
                summary=summary,
                status="ready",
                metadata={"bucket": bucket_key, "note_count": len(snotes)},
            )
            citations = [
                {"source_kind": "atomic_note", "source_id": str(n["id"]), "weight": 1.0}
                for n in snotes
                if n.get("id")
            ]
            if bucket_key.startswith("agent:"):
                citations.append(
                    {
                        "source_kind": "agent",
                        "source_id": bucket_key.split(":", 1)[1],
                        "weight": 1.0,
                    }
                )
            inserted = replace_wiki_page_sources(
                database_url, wiki_page_id=page_id, sources=citations
            )
            stats["citations_added"] += inserted
            stats["pages_created" if action == "created" else "pages_updated"] += 1
            insert_wiki_mutation(
                database_url,
                wiki_job_id=job_id,
                wiki_page_id=page_id,
                mutation_type=(
                    "page_created" if action == "created" else "page_updated"
                ),
                payload={"page_type": "source_summary", "bucket": bucket_key},
            )
            produced.append({"page_type": "source_summary", "slug": slug, "title": title})
            await _progress(
                redis,
                job_id=job_id,
                percent=15 + int(60 * current_index / max(candidate_total, 1)),
                current=current_index,
                total=candidate_total,
                stats=stats,
            )
            await _log(
                redis,
                job_id=job_id,
                message=f"{action} source-summary page “{title}” ({len(snotes)} note(s))",
                data={"slug": slug, "bucket": bucket_key},
            )

        # ----- Synthesis page -----
        current_index += 1
        topic_counts = {k: len(v) for k, v in by_tag.items()}
        source_counts = {k: len(v) for k, v in by_source.items()}
        s_title, s_summary, s_body = _compose_synthesis_page(
            scope_label=scope_label,
            note_count=len(notes),
            topic_counts=topic_counts,
            source_counts=source_counts,
        )
        synth_id, action = upsert_wiki_page(
            database_url,
            wiki_space_id=wiki_space_id,
            slug="synthesis",
            title=s_title,
            page_type="synthesis",
            body=s_body,
            summary=s_summary,
            status="ready",
            metadata={
                "scope": scope_label,
                "topics": len(topic_counts),
                "sources": len(source_counts),
            },
        )
        stats["pages_created" if action == "created" else "pages_updated"] += 1
        insert_wiki_mutation(
            database_url,
            wiki_job_id=job_id,
            wiki_page_id=synth_id,
            mutation_type=("page_created" if action == "created" else "page_updated"),
            payload={"page_type": "synthesis"},
        )

        await _log(
            redis,
            job_id=job_id,
            message=f"{action} synthesis page",
        )
        if redis:
            await record_metric(
                redis, job_id=job_id, name="pages_created", value=stats["pages_created"], stage=STAGE
            )
            await record_metric(
                redis, job_id=job_id, name="pages_updated", value=stats["pages_updated"], stage=STAGE
            )

        # ----- Index page (built from now-current pages) -----
        current_index += 1
        all_pages = list_wiki_pages(database_url, wiki_space_id=wiki_space_id)
        i_title, i_summary, i_body = _compose_index_page(pages=all_pages)
        idx_id, action = upsert_wiki_page(
            database_url,
            wiki_space_id=wiki_space_id,
            slug="index",
            title=i_title,
            page_type="index",
            body=i_body,
            summary=i_summary,
            status="ready",
            metadata={"page_count": len(all_pages)},
        )
        stats["pages_created" if action == "created" else "pages_updated"] += 1
        insert_wiki_mutation(
            database_url,
            wiki_job_id=job_id,
            wiki_page_id=idx_id,
            mutation_type=("page_created" if action == "created" else "page_updated"),
            payload={"page_type": "index", "page_count": len(all_pages)},
        )
        await _log(
            redis,
            job_id=job_id,
            message=f"{action} index page ({len(all_pages)} entries)",
        )

        # ----- Changelog page (append) -----
        current_index += 1
        existing_changelog = next(
            (p.get("body") for p in all_pages if p.get("slug") == "changelog"),
            None,
        )
        c_title, c_summary, c_body = _compose_changelog_page(
            job_id=job_id,
            started_iso=started_iso,
            stats=stats,
            existing_body=existing_changelog if isinstance(existing_changelog, str) else None,
        )
        chg_id, action = upsert_wiki_page(
            database_url,
            wiki_space_id=wiki_space_id,
            slug="changelog",
            title=c_title,
            page_type="changelog",
            body=c_body,
            summary=c_summary,
            status="ready",
        )
        stats["pages_created" if action == "created" else "pages_updated"] += 1
        insert_wiki_mutation(
            database_url,
            wiki_job_id=job_id,
            wiki_page_id=chg_id,
            mutation_type=("page_created" if action == "created" else "page_updated"),
            payload={"page_type": "changelog"},
        )
        await _log(redis, job_id=job_id, message=f"{action} changelog page")

        await _progress(
            redis,
            job_id=job_id,
            percent=95,
            current=candidate_total,
            total=candidate_total,
            stats=stats,
        )

        update_wiki_job_status(
            database_url,
            job_id=job_id,
            status=WIKI_JOB_STATUS_SUCCEEDED,
            stats=stats,
        )
        update_wiki_space_status(
            database_url, space_id=wiki_space_id, status="ready", mark_generated=True
        )
        await _finish(redis, job_id=job_id, status=WIKI_JOB_STATUS_SUCCEEDED, stats=stats)

    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "wiki_generation_failed",
            workspace_id=workspace_id,
            wiki_space_id=wiki_space_id,
            error=str(exc),
        )
        reason = str(exc)[:2000]
        update_wiki_job_status(
            database_url,
            job_id=job_id,
            status=WIKI_JOB_STATUS_FAILED,
            stats=stats,
            failure_reason=reason,
        )
        update_wiki_space_status(database_url, space_id=wiki_space_id, status="failed")
        await _finish(
            redis,
            job_id=job_id,
            status=WIKI_JOB_STATUS_FAILED,
            stats=stats,
            failure_reason=reason,
        )
        raise
