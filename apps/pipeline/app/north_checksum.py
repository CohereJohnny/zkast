"""Canonical content checksums for North conversation payloads (import dedup)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.transcript_episodes import build_episode_rows_from_transcript

ZKAST_META_KEY = "_zkast"


def north_conversation_conv_root(raw: dict[str, Any] | list[Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {"messages": raw}
    return {"messages": []}


def north_conversation_content_checksum(raw: dict[str, Any] | list[Any]) -> str:
    """SHA-256 of UTF-8 JSON — must match ``post_north_conversation_import``."""
    conv_root = north_conversation_conv_root(raw)
    raw_bytes = json.dumps(conv_root, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()


def cache_payload_has_transcript_messages(payload: dict[str, Any]) -> bool:
    """True when cached payload includes a message list (full transcript shape)."""
    msgs = payload.get("messages")
    if isinstance(msgs, list) and len(msgs) > 0:
        return True
    for key in ("turns", "items", "history"):
        block = payload.get(key)
        if isinstance(block, list) and len(block) > 0:
            return True
    return False


def text_content_hash(text: str) -> str:
    """SHA-256 of normalized ingestible text (episode, note input, etc.)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def north_ingest_content_hash(
    raw: dict[str, Any] | list[Any],
    *,
    import_settings: dict[str, Any] | None,
    north_metadata: dict[str, Any] | None,
) -> str:
    """Hash of ingestible episode bodies — stable across JSON wrapper differences."""
    root = north_conversation_conv_root(raw)
    rows = build_episode_rows_from_transcript(
        workspace_id="00000000-0000-0000-0000-000000000001",
        document_id="00000000-0000-0000-0000-000000000002",
        ingestion_run_id="00000000-0000-0000-0000-000000000003",
        agent_id="00000000-0000-0000-0000-000000000004",
        raw_transcript=root,
        import_settings=import_settings,
        north_metadata=north_metadata,
    )
    if not rows:
        return ""
    episode_hashes = sorted(text_content_hash(str(r[1])) for r in rows)
    return hashlib.sha256("\n".join(episode_hashes).encode("utf-8")).hexdigest()


def zkast_meta(payload: dict[str, Any]) -> dict[str, Any]:
    block = payload.get(ZKAST_META_KEY)
    return dict(block) if isinstance(block, dict) else {}


def cache_ingest_hash_from_payload(payload: dict[str, Any]) -> str | None:
    stored = zkast_meta(payload).get("ingest_content_hash")
    return str(stored) if stored else None


def stamp_cache_payload_ingest_hash(
    payload: dict[str, Any],
    *,
    import_settings: dict[str, Any] | None,
    north_metadata: dict[str, Any] | None,
    full_transcript: bool = False,
) -> dict[str, Any]:
    """Attach ingest hash metadata when the cache holds a full transcript."""
    if not cache_payload_has_transcript_messages(payload):
        return payload
    ingest_hash = north_ingest_content_hash(
        payload,
        import_settings=import_settings,
        north_metadata=north_metadata,
    )
    if not ingest_hash:
        return payload
    out = dict(payload)
    zk = dict(zkast_meta(out))
    zk["ingest_content_hash"] = ingest_hash
    if full_transcript:
        zk["full_transcript"] = True
    out[ZKAST_META_KEY] = zk
    return out
