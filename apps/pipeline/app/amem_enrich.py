"""Post-ingestion A-MEM-style enrichment (keywords + one-line context)."""

from __future__ import annotations

import json
import re
from typing import Any

import structlog
from openai import AsyncOpenAI

from app.graphiti_factory import COHERE_COMPAT_BASE
from app.notes_repo import fetch_note, patch_note_derivations

logger = structlog.get_logger(__name__)


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
) -> None:
    if not note_ids:
        return
    notes_payload: list[dict[str, str]] = []
    for nid in note_ids:
        n = fetch_note(database_url, workspace_id=workspace_id, note_id=nid)
        if not n:
            continue
        notes_payload.append(
            {
                "note_id": nid,
                "title": str(n.get("title") or "")[:200],
                "body": str(n.get("body") or "")[:6000],
            }
        )
    if not notes_payload:
        return

    system = (
        "You enrich atomic notes for an agentic memory system. "
        "For each note, propose 3-12 lowercase memory_keywords (concepts) "
        "and one concise memory_context sentence (max 240 chars). "
        "Output strict JSON: {\"items\":[{\"note_id\":\"uuid\",\"memory_keywords\":[\"a\"],"
        "\"memory_context\":\"...\"}]}"
    )
    user = json.dumps({"notes": notes_payload}, ensure_ascii=False)

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=COHERE_COMPAT_BASE,
        timeout=120.0,
        max_retries=1,
    )
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.15,
        response_format={"type": "json_object"},
    )
    raw_text = resp.choices[0].message.content or ""
    if not raw_text.strip():
        logger.warning("amem_enrich_empty_response", note_count=len(notes_payload))
        return
    data = _extract_json_object(raw_text)
    items = list(data.get("items") or [])
    for it in items:
        nid = str(it.get("note_id") or "")
        if not nid:
            continue
        kws = [str(x).strip().lower() for x in (it.get("memory_keywords") or []) if str(x).strip()]
        ctx = str(it.get("memory_context") or "").strip()[:2000]
        if not kws and not ctx:
            continue
        patch_note_derivations(
            database_url,
            workspace_id=workspace_id,
            note_id=nid,
            memory_context=ctx or None,
            memory_keywords=kws or None,
        )
