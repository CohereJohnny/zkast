"""North / agent transcript → episodes (turn windows, optional message mode)."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4


def _extract_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" and block.get("text"):
                    parts.append(str(block["text"]))
                elif block.get("text"):
                    parts.append(str(block["text"]))
        return "\n".join(p for p in parts if p).strip()
    return ""


def _normalize_messages(raw: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    """Accept either {messages: [...]} or a bare list."""
    if isinstance(raw, list):
        return [dict(m) for m in raw if isinstance(m, dict)]
    msgs = raw.get("messages") or raw.get("data") or raw.get("items") or []
    if not isinstance(msgs, list):
        return []
    return [dict(m) for m in msgs if isinstance(m, dict)]


def _message_role(msg: dict[str, Any]) -> str:
    return str(msg.get("role") or "unknown").lower()


def _message_classes(msg: dict[str, Any]) -> set[str]:
    classes: set[str] = {_message_role(msg)}
    if msg.get("tool_calls"):
        classes.add("tool_call")
    if msg.get("error"):
        classes.add("error")
    if msg.get("citations") or msg.get("files"):
        classes.add("citation")
    meta = msg.get("metadata") or {}
    if isinstance(meta, dict) and str(meta.get("kind") or "").lower() == "reasoning":
        classes.add("reasoning")
    return classes


def _default_include_roles() -> set[str]:
    return {"user", "assistant", "tool"}


def _default_exclude_roles() -> set[str]:
    return {"system"}


def filter_messages(
    messages: list[dict[str, Any]],
    import_settings: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    settings = import_settings or {}
    include = {str(x).lower() for x in (settings.get("include_roles") or _default_include_roles())}
    exclude = {str(x).lower() for x in (settings.get("exclude_roles") or _default_exclude_roles())}
    reasoning = bool(settings.get("include_reasoning_traces"))
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = _message_role(msg)
        if role in exclude:
            continue
        cls = _message_classes(msg)
        if not reasoning and "reasoning" in cls:
            continue
        if role == "tool":
            if "tool" not in include:
                continue
        elif role not in include:
            continue
        out.append(msg)
    return out


def _render_turn_block(
    *,
    agent_name: str,
    external_agent_id: str,
    conversation_title: str,
    turn_index: int,
    turn_messages: list[dict[str, Any]],
    ingested_classes: set[str],
) -> str:
    lines: list[str] = [
        f"Agent: {agent_name} ({external_agent_id})",
        f"Conversation: {conversation_title}",
        f"Turn index: {turn_index}",
        f"Ingested message classes: {', '.join(sorted(ingested_classes))}",
        "",
    ]
    for msg in turn_messages:
        role = _message_role(msg)
        body = _extract_text_from_content(msg.get("content"))
        if body:
            lines.append(f"{role.upper()}: {body}")
        if msg.get("tool_calls"):
            try:
                lines.append(f"TOOL_CALLS: {json.dumps(msg.get('tool_calls'), ensure_ascii=False)[:4000]}")
            except (TypeError, ValueError):
                lines.append("TOOL_CALLS: [unserializable]")
        if msg.get("error"):
            lines.append(f"ERROR: {msg.get('error')}")
    lines.append("")
    lines.append("Outcome: (see thread above)")
    return "\n".join(lines).strip()


def _turn_windows(filtered: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group messages into turns: a user message opens a turn; following msgs attach until next user."""
    windows: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for msg in filtered:
        role = _message_role(msg)
        if role == "user" and current:
            windows.append(current)
            current = []
        current.append(msg)
    if current:
        windows.append(current)
    if not windows and filtered:
        return [filtered]
    return windows


def build_episode_rows_from_transcript(
    *,
    workspace_id: str,
    document_id: str,
    ingestion_run_id: str,
    agent_id: str,
    raw_transcript: dict[str, Any] | list[Any],
    import_settings: dict[str, Any] | None,
    north_metadata: dict[str, Any] | None,
) -> list[tuple[str, str, int, int, int, str, str | None]]:
    """Return rows for ``documents_repo.insert_episodes``."""
    _ = workspace_id, document_id, ingestion_run_id  # reserved for provenance headers
    meta = north_metadata or {}
    agent_name = str(meta.get("agent_display_name") or "Agent")
    external_agent_id = str(meta.get("north_external_agent_id") or "")
    conv_title = meta.get("conversation_title") or meta.get("title")
    if not conv_title and isinstance(raw_transcript, dict):
        conv_title = raw_transcript.get("title")
    conversation_title = str(conv_title or "Conversation")
    mode = str((import_settings or {}).get("segmentation_mode") or "turn")
    messages = _normalize_messages(raw_transcript)
    filtered = filter_messages(messages, import_settings)
    rows: list[tuple[str, str, int, int, int, str, str | None]] = []
    sequence = 0

    if mode == "message":
        for i, msg in enumerate(filtered):
            classes = _message_classes(msg)
            text = _render_turn_block(
                agent_name=agent_name,
                external_agent_id=external_agent_id,
                conversation_title=conversation_title,
                turn_index=i + 1,
                turn_messages=[msg],
                ingested_classes=classes,
            )
            if not text.strip():
                continue
            rows.append((str(uuid4()), text, i + 1, i + 1, sequence, "north_message", agent_id))
            sequence += 1
        return rows

    windows = _turn_windows(filtered)
    for i, turn in enumerate(windows):
        classes: set[str] = set()
        for msg in turn:
            classes |= _message_classes(msg)
        text = _render_turn_block(
            agent_name=agent_name,
            external_agent_id=external_agent_id,
            conversation_title=conversation_title,
            turn_index=i + 1,
            turn_messages=turn,
            ingested_classes=classes,
        )
        if not text.strip():
            continue
        rows.append((str(uuid4()), text, i + 1, i + 1, sequence, "north_turn_window", agent_id))
        sequence += 1
    return rows


def count_north_episode_rows_from_conversation(
    *,
    conv: dict[str, Any] | list[Any],
    import_settings: dict[str, Any] | None,
    north_metadata: dict[str, Any] | None,
) -> int:
    """Dry-run episode count using the same rules as ingestion (filters + segmentation).

    Used to reject imports before creating a document when filters would yield zero episodes.
    Placeholder UUIDs are ignored; only message content and settings affect the count.
    """
    root: dict[str, Any]
    if isinstance(conv, dict):
        root = conv
    elif isinstance(conv, list):
        root = {"messages": conv}
    else:
        root = {"messages": []}
    rows = build_episode_rows_from_transcript(
        workspace_id="00000000-0000-0000-0000-000000000001",
        document_id="00000000-0000-0000-0000-000000000002",
        ingestion_run_id="00000000-0000-0000-0000-000000000003",
        agent_id="00000000-0000-0000-0000-000000000004",
        raw_transcript=root,
        import_settings=import_settings,
        north_metadata=north_metadata,
    )
    return len(rows)


def _parse_ts_to_iso(v: Any) -> str | None:
    """Normalize North/API timestamps for metadata (ISO-friendly string)."""
    import datetime as dt_mod

    if v is None:
        return None
    if isinstance(v, dt_mod.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=dt_mod.timezone.utc)
        return v.isoformat()
    if isinstance(v, dt_mod.date):
        return dt_mod.datetime.combine(v, dt_mod.time.min, tzinfo=dt_mod.timezone.utc).isoformat()
    if isinstance(v, (int, float)):
        try:
            ts = float(v)
            # Heuristic: millis vs seconds
            if ts > 1e12:
                ts /= 1000.0
            return dt_mod.datetime.fromtimestamp(ts, tz=dt_mod.timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v).strip()
    if not s:
        return None
    try:
        normalized = s.replace("Z", "+00:00") if s.endswith("Z") else s
        parsed = dt_mod.datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_mod.timezone.utc)
        return parsed.isoformat()
    except ValueError:
        return None


def north_conversation_activity_iso(raw: dict[str, Any] | list[Any]) -> str | None:
    """Best-effort activity time from a North conversation payload (for UI metadata)."""
    root: dict[str, Any]
    if isinstance(raw, dict):
        root = raw
    elif isinstance(raw, list):
        root = {"messages": raw}
    else:
        return None
    for key in (
        "updatedAt",
        "updated_at",
        "lastActivityAt",
        "last_activity_at",
        "lastMessageAt",
        "last_message_at",
        "createdAt",
        "created_at",
    ):
        iso = _parse_ts_to_iso(root.get(key))
        if iso:
            return iso
    messages = _normalize_messages(root)
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        for mk in ("timestamp", "createdAt", "created_at", "time", "ts", "postedAt"):
            iso = _parse_ts_to_iso(msg.get(mk))
            if iso:
                return iso
    return None


def transcript_preview_snippet(raw: dict[str, Any] | list[Any], *, max_chars: int = 8000) -> str:
    """Plain preview for UI (not an episode)."""
    messages = _normalize_messages(raw)
    lines: list[str] = []
    for msg in messages[:80]:
        role = _message_role(msg)
        body = _extract_text_from_content(msg.get("content"))[:500]
        if body:
            lines.append(f"{role}: {body}")
    text = "\n".join(lines)
    return text[:max_chars]


def north_conversation_preview_payload(
    raw: dict[str, Any] | list[Any],
    *,
    max_messages: int = 50,
    max_excerpt_chars: int = 600,
) -> dict[str, Any]:
    """Structured preview for agent UI (role + excerpt per message, capped)."""
    if isinstance(raw, dict):
        root = raw
    elif isinstance(raw, list):
        root = {"messages": raw}
    else:
        root = {"messages": []}
    title = str(root.get("title") or root.get("name") or "").strip()
    messages = _normalize_messages(root)
    items: list[dict[str, str]] = []
    for msg in messages[:max_messages]:
        role = _message_role(msg)
        body = _extract_text_from_content(msg.get("content"))
        if len(body) > max_excerpt_chars:
            excerpt = body[:max_excerpt_chars] + "…"
        else:
            excerpt = body
        items.append({"role": role, "excerpt": excerpt})
    return {
        "title": title,
        "message_count": len(messages),
        "preview_message_limit": max_messages,
        "preview_truncated": len(messages) > max_messages,
        "messages": items,
    }
