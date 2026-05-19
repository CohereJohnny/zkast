"""Post-ingestion A-MEM-style enrichment (keywords + one-line context)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog
from openai import AsyncOpenAI

from app.graphiti_factory import COHERE_COMPAT_BASE
from app.notes_repo import fetch_note, patch_note_derivations

logger = structlog.get_logger(__name__)

AMEM_ENRICH_BATCH_SIZE = 12

LogFn = Callable[..., Awaitable[None]]


@dataclass
class AmemEnrichResult:
    requested: int = 0
    enriched: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _extract_json_object(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise
        return json.loads(m.group(0))


async def enrich_notes_amem_batch(
    *,
    api_key: str,
    model: str,
    database_url: str,
    workspace_id: str,
    note_ids: list[str],
    on_log: LogFn | None = None,
) -> AmemEnrichResult:
    """Enrich North-derived notes with memory keywords, context, and optional tags."""
    result = AmemEnrichResult(requested=len(note_ids))
    if not note_ids:
        return result

    async def _log(level: str, message: str, **data: Any) -> None:
        if on_log:
            await on_log(level=level, message=message, data=data or None)

    for batch_start in range(0, len(note_ids), AMEM_ENRICH_BATCH_SIZE):
        batch_ids = note_ids[batch_start : batch_start + AMEM_ENRICH_BATCH_SIZE]
        notes_payload: list[dict[str, Any]] = []
        before_body: dict[str, str] = {}
        for nid in batch_ids:
            n = fetch_note(database_url, workspace_id=workspace_id, note_id=nid)
            if not n:
                result.skipped += 1
                continue
            body = str(n.get("body") or "")
            before_body[nid] = body
            notes_payload.append(
                {
                    "note_id": nid,
                    "title": str(n.get("title") or "")[:200],
                    "body": body[:6000],
                    "existing_tags": list(n.get("tags") or [])[:20],
                }
            )
        if not notes_payload:
            continue

        system = (
            "You enrich atomic notes for an agentic memory system. "
            "For each note, propose 3-12 lowercase memory_keywords (concepts), "
            "one concise memory_context sentence (max 240 chars), and 0-6 optional "
            "lowercase tags that complement existing_tags (do not repeat existing_tags). "
            'Output strict JSON: {"items":[{"note_id":"uuid","memory_keywords":["a"],'
            '"memory_context":"...","tags":["optional"]}]}'
        )
        user = json.dumps({"notes": notes_payload}, ensure_ascii=False)

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=COHERE_COMPAT_BASE,
            timeout=120.0,
            max_retries=1,
        )
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.15,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"A-MEM enrich batch failed: {exc}"
            logger.warning("amem_enrich_batch_failed", error=str(exc), batch=len(batch_ids))
            result.failed += len(batch_ids)
            result.errors.append(msg)
            await _log("warning", msg, batch_size=len(batch_ids))
            continue

        raw_text = resp.choices[0].message.content or ""
        if not raw_text.strip():
            result.failed += len(batch_ids)
            result.errors.append("A-MEM enrich returned empty LLM response")
            await _log(
                "warning",
                "A-MEM enrich returned empty response",
                batch_size=len(batch_ids),
            )
            continue

        try:
            data = _extract_json_object(raw_text)
        except (json.JSONDecodeError, ValueError) as exc:
            result.failed += len(batch_ids)
            result.errors.append(f"A-MEM enrich JSON parse failed: {exc}")
            await _log("warning", "A-MEM enrich JSON parse failed", error=str(exc))
            continue

        items = list(data.get("items") or [])
        seen_ids = {str(it.get("note_id") or "") for it in items if it.get("note_id")}
        for nid in batch_ids:
            if nid not in seen_ids and nid in before_body:
                result.skipped += 1

        for it in items:
            nid = str(it.get("note_id") or "")
            if not nid or nid not in before_body:
                result.skipped += 1
                continue
            kws = [
                str(x).strip().lower()
                for x in (it.get("memory_keywords") or [])
                if str(x).strip()
            ]
            ctx = str(it.get("memory_context") or "").strip()[:2000]
            tag_adds = [
                str(x).strip().lower()
                for x in (it.get("tags") or [])
                if str(x).strip()
            ]
            if not kws and not ctx and not tag_adds:
                result.skipped += 1
                continue
            patch_note_derivations(
                database_url,
                workspace_id=workspace_id,
                note_id=nid,
                memory_context=ctx or None,
                memory_keywords=kws or None,
                tags=tag_adds or None,
                merge_tags=bool(tag_adds),
                mark_dreaming_touch=False,
            )
            after = fetch_note(database_url, workspace_id=workspace_id, note_id=nid)
            if after and str(after.get("body") or "") != before_body[nid]:
                result.failed += 1
                result.errors.append(f"Note body changed during enrich: {nid[:8]}")
                await _log(
                    "error",
                    "A-MEM enrich mutated note body (blocked)",
                    note_id=nid,
                )
                continue
            result.enriched += 1

    if result.enriched:
        await _log(
            "info",
            f"A-MEM enriched {result.enriched} note(s)",
            enriched=result.enriched,
            skipped=result.skipped,
            failed=result.failed,
        )
    return result
