"""Import status for North conversations (ingest-content hash vs imported documents)."""

from __future__ import annotations

import hashlib
from typing import Any

from app.north_checksum import (
    cache_ingest_hash_from_payload,
    cache_payload_has_transcript_messages,
    north_ingest_content_hash,
    stamp_cache_payload_ingest_hash,
    zkast_meta,
)

PROCESSING_DOC_STATUSES = frozenset(
    {
        "queued",
        "parsing",
        "generating_notes",
        "extracting_graph",
        "building_graph",
    },
)

ImportState = str  # not_imported | processing | current | stale | imported
SyncStatus = str  # not_synced | synced | syncing | outdated


def sync_status_from_import_state(import_state: ImportState) -> SyncStatus:
    """Single user-facing sync label (replaces Imported vs Up to date split)."""
    if import_state in ("current", "imported"):
        return "synced"
    if import_state == "processing":
        return "syncing"
    if import_state == "stale":
        return "outdated"
    return "not_synced"


def north_conversation_id_from_row(row: dict[str, Any]) -> str:
    return str(
        row.get("north_conversation_id")
        or row.get("id")
        or row.get("conversation_id")
        or row.get("conversationId")
        or row.get("thread_id")
        or row.get("threadId")
        or "",
    ).strip()


def payload_from_conversation_row(row: dict[str, Any]) -> dict[str, Any] | None:
    pl = row.get("payload")
    if isinstance(pl, dict):
        return pl
    if row.get("north_conversation_id"):
        return None
    if north_conversation_id_from_row(row):
        return dict(row)
    return None


def imported_ingest_hash(doc: dict[str, Any]) -> str | None:
    meta = doc.get("north_metadata")
    if isinstance(meta, dict):
        stored = meta.get("ingest_content_hash")
        if stored:
            return str(stored)
    return None


def compute_cache_ingest_hash(
    cache_payload: dict[str, Any],
    *,
    import_settings: dict[str, Any] | None,
    north_metadata: dict[str, Any] | None,
) -> str | None:
    """Only compare when cache was import-stamped (avoids list-vs-full JSON false stale)."""
    stored = cache_ingest_hash_from_payload(cache_payload)
    if stored:
        return stored
    if not zkast_meta(cache_payload).get("full_transcript"):
        return None
    if not cache_payload_has_transcript_messages(cache_payload):
        return None
    computed = north_ingest_content_hash(
        cache_payload,
        import_settings=import_settings,
        north_metadata=north_metadata,
    )
    return computed or None


def resolve_import_state(
    *,
    doc: dict[str, Any] | None,
    cache_payload: dict[str, Any] | None,
    import_settings: dict[str, Any] | None = None,
    north_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return import_status metadata for one conversation."""
    if doc is None:
        out: dict[str, Any] = {
            "import_state": "not_imported",
            "sync_status": "not_synced",
            "document_id": None,
            "document_status": None,
            "imported_checksum": None,
            "ingest_content_hash": None,
            "cache_ingest_hash": None,
            "memory": None,
        }
        if cache_payload is not None:
            out["cache_ingest_hash"] = compute_cache_ingest_hash(
                cache_payload,
                import_settings=import_settings,
                north_metadata=north_metadata,
            )
        return out

    doc_status = str(doc.get("status") or "")
    doc_id = str(doc.get("id") or "")
    imported_hash = imported_ingest_hash(doc)

    cache_hash: str | None = None
    if cache_payload is not None:
        cache_hash = compute_cache_ingest_hash(
            cache_payload,
            import_settings=import_settings,
            north_metadata=north_metadata,
        )

    if doc_status in PROCESSING_DOC_STATUSES:
        import_state: ImportState = "processing"
    elif imported_hash and cache_hash:
        import_state = "current" if cache_hash == imported_hash else "stale"
    else:
        import_state = "imported"

    return {
        "import_state": import_state,
        "sync_status": sync_status_from_import_state(import_state),
        "document_id": doc_id or None,
        "document_status": doc_status or None,
        "imported_checksum": str(doc.get("checksum") or "") or None,
        "ingest_content_hash": imported_hash,
        "cache_ingest_hash": cache_hash,
        "memory": None,
    }


def attach_import_status_to_conversations(
    items: list[dict[str, Any]],
    docs_by_conversation_id: dict[str, dict[str, Any]],
    *,
    import_settings: dict[str, Any] | None = None,
    agent_north_metadata: dict[str, Any] | None = None,
    memory_stats_by_conversation: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    mem = memory_stats_by_conversation or {}
    for row in items:
        cid = north_conversation_id_from_row(row)
        payload = payload_from_conversation_row(row)
        doc = docs_by_conversation_id.get(cid) if cid else None
        status = resolve_import_state(
            doc=doc,
            cache_payload=payload,
            import_settings=import_settings,
            north_metadata=agent_north_metadata,
        )
        if status.get("sync_status") in ("synced", "syncing", "outdated") and cid in mem:
            status["memory"] = dict(mem[cid])
        elif status.get("sync_status") == "not_synced" and row.get("fetched_at"):
            status["memory"] = {"cached": True}
        enriched.append({**row, **status})
    return enriched


def agent_import_digest(docs_by_conversation_id: dict[str, dict[str, Any]]) -> str | None:
    """Stable digest of imported ingest hashes (fallback: storage checksum)."""
    if not docs_by_conversation_id:
        return None
    parts: list[str] = []
    for cid, doc in sorted(docs_by_conversation_id.items()):
        ingest = imported_ingest_hash(doc)
        token = ingest or str(doc.get("checksum") or "")
        if token:
            parts.append(f"{cid}:{token}")
    if not parts:
        return None
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
