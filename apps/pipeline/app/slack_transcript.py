"""Slack channel → conversation units → episode rows.

Segmentation (decided with real-channel data):
- **Threads** (a root message with replies) → one conversation unit each.
- **Standalone** messages → grouped into **session** units split on a quiet gap
  (default 30 min) so a natural conversation becomes one document.

Noise filtering drops channel join/leave, empty, and pure system messages.
``<@U…>`` user mentions and ``<#C…|name>`` channel mentions are resolved to
readable names so derived notes and graph extraction read naturally.

Import normalizes messages and stores them on the document
(``raw_transcript_json``); the worker's parse step turns a stored unit into
episodes offline (no Slack calls), mirroring the North transcript flow.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

# Subtypes that are pure channel noise (no knowledge value).
_NOISE_SUBTYPES: frozenset[str] = frozenset(
    {
        "channel_join",
        "channel_leave",
        "channel_topic",
        "channel_purpose",
        "channel_name",
        "channel_archive",
        "channel_unarchive",
        "group_join",
        "group_leave",
        "bot_add",
        "bot_remove",
        "pinned_item",
        "reminder_add",
    }
)

DEFAULT_SESSION_GAP_SECONDS = 1800  # 30 min quiet gap starts a new session unit.

_MENTION_RE = re.compile(r"<@([A-Z0-9]+)>")
_CHANNEL_RE = re.compile(r"<#([A-Z0-9]+)\|([^>]*)>")
_LINK_RE = re.compile(r"<(https?://[^|>]+)\|([^>]+)>")
_BARE_LINK_RE = re.compile(r"<(https?://[^>]+)>")


def _msg_ts(msg: dict[str, Any]) -> float:
    try:
        return float(str(msg.get("ts") or "0"))
    except (TypeError, ValueError):
        return 0.0


def message_is_noise(msg: dict[str, Any]) -> bool:
    subtype = str(msg.get("subtype") or "").strip()
    if subtype in _NOISE_SUBTYPES:
        return True
    text = str(msg.get("text") or "").strip()
    has_attachments = bool(msg.get("attachments") or msg.get("files") or msg.get("blocks"))
    return not text and not has_attachments


def resolve_text(text: str, user_names: dict[str, str]) -> str:
    """Resolve Slack mention/link markup to readable text."""
    if not text:
        return ""

    def _user(m: re.Match[str]) -> str:
        uid = m.group(1)
        return "@" + (user_names.get(uid) or uid)

    out = _MENTION_RE.sub(_user, text)
    out = _CHANNEL_RE.sub(lambda m: "#" + (m.group(2) or m.group(1)), out)
    out = _LINK_RE.sub(lambda m: f"{m.group(2)} ({m.group(1)})", out)
    out = _BARE_LINK_RE.sub(lambda m: m.group(1), out)
    return out.strip()


def _normalize_message(msg: dict[str, Any], user_names: dict[str, str]) -> dict[str, Any]:
    uid = str(msg.get("user") or msg.get("bot_id") or "").strip()
    name = user_names.get(uid) or str(msg.get("username") or "").strip() or uid or "unknown"
    ts = str(msg.get("ts") or "")
    when = ""
    try:
        when = datetime.fromtimestamp(float(ts), tz=UTC).isoformat() if ts else ""
    except (TypeError, ValueError):
        when = ""
    return {
        "ts": ts,
        "at": when,
        "user": uid,
        "user_name": name,
        "text": resolve_text(str(msg.get("text") or ""), user_names),
    }


def _filtered_sorted(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = [m for m in messages if not message_is_noise(m)]
    return sorted(kept, key=_msg_ts)


def build_conversation_units(
    *,
    channel_id: str,
    channel_name: str,
    root_messages: list[dict[str, Any]],
    replies_by_thread_ts: dict[str, list[dict[str, Any]]],
    user_names: dict[str, str],
    session_gap_seconds: int = DEFAULT_SESSION_GAP_SECONDS,
) -> list[dict[str, Any]]:
    """Group channel messages into thread + session conversation units.

    Returns units shaped for document creation:
    ``{external_conversation_id, kind, title, anchor_ts, transcript}`` where
    ``transcript = {channel_id, channel_name, kind, title, messages:[…]}``.
    """
    units: list[dict[str, Any]] = []
    standalone: list[dict[str, Any]] = []

    for root in _filtered_sorted(root_messages):
        thread_ts = str(root.get("thread_ts") or root.get("ts") or "")
        reply_count = int(root.get("reply_count") or 0)
        is_thread_parent = reply_count > 0 or thread_ts in replies_by_thread_ts
        if is_thread_parent:
            raw = replies_by_thread_ts.get(thread_ts) or [root]
            msgs = [_normalize_message(m, user_names) for m in _filtered_sorted(raw)]
            msgs = [m for m in msgs if m["text"] or m["user_name"]]
            if not msgs:
                continue
            title = _unit_title(channel_name, msgs[0], kind="thread")
            units.append(
                {
                    "external_conversation_id": f"{channel_id}:{thread_ts}",
                    "kind": "thread",
                    "title": title,
                    "anchor_ts": thread_ts,
                    "transcript": {
                        "channel_id": channel_id,
                        "channel_name": channel_name,
                        "kind": "thread",
                        "title": title,
                        "messages": msgs,
                    },
                }
            )
        else:
            standalone.append(root)

    # Session-group standalone messages on a quiet gap.
    session: list[dict[str, Any]] = []
    prev_ts: float | None = None
    for msg in _filtered_sorted(standalone):
        ts = _msg_ts(msg)
        if prev_ts is not None and (ts - prev_ts) > session_gap_seconds and session:
            units.append(_session_unit(channel_id, channel_name, session, user_names))
            session = []
        session.append(msg)
        prev_ts = ts
    if session:
        units.append(_session_unit(channel_id, channel_name, session, user_names))

    units.sort(key=lambda u: float(u.get("anchor_ts") or 0))
    return units


def _session_unit(
    channel_id: str,
    channel_name: str,
    raw_messages: list[dict[str, Any]],
    user_names: dict[str, str],
) -> dict[str, Any]:
    msgs = [_normalize_message(m, user_names) for m in raw_messages]
    msgs = [m for m in msgs if m["text"] or m["user_name"]]
    anchor_ts = msgs[0]["ts"] if msgs else (str(_msg_ts(raw_messages[0])) if raw_messages else "0")
    title = _unit_title(channel_name, msgs[0] if msgs else {}, kind="session")
    return {
        "external_conversation_id": f"{channel_id}:session:{anchor_ts}",
        "kind": "session",
        "title": title,
        "anchor_ts": anchor_ts,
        "transcript": {
            "channel_id": channel_id,
            "channel_name": channel_name,
            "kind": "session",
            "title": title,
            "messages": msgs,
        },
    }


def _unit_title(channel_name: str, first_msg: dict[str, Any], *, kind: str) -> str:
    when = str(first_msg.get("at") or "")[:10]
    label = "thread" if kind == "thread" else "session"
    return f"#{channel_name} {label} {when}".strip()


def render_unit_text(transcript: dict[str, Any]) -> str:
    """Render a conversation unit into a single episode body."""
    lines: list[str] = []
    channel = str(transcript.get("channel_name") or transcript.get("channel_id") or "")
    if channel:
        lines.append(f"Channel: #{channel}")
    title = str(transcript.get("title") or "")
    if title:
        lines.append(f"Conversation: {title}")
    lines.append("")
    for m in transcript.get("messages") or []:
        text = str(m.get("text") or "").strip()
        if not text:
            continue
        who = str(m.get("user_name") or "unknown")
        lines.append(f"{who}: {text}")
    return "\n".join(lines).strip()


def build_episode_rows_from_slack_unit(
    *,
    transcript: dict[str, Any],
    agent_id: str,
    segmentation_mode: str = "turn",
) -> list[tuple[str, str, int, int, int, str, str | None]]:
    """Episode rows for ``documents_repo.insert_episodes``.

    - ``turn`` (default): the whole unit becomes one ``slack_turn_window`` episode.
    - ``message``: one ``slack_message`` episode per message.
    Row shape matches the North builder: ``(id, text, page_start, page_end,
    sequence, kind, agent_id)``.
    """
    rows: list[tuple[str, str, int, int, int, str, str | None]] = []
    messages = transcript.get("messages") or []
    if segmentation_mode == "message":
        seq = 0
        channel = str(transcript.get("channel_name") or "")
        for m in messages:
            text = str(m.get("text") or "").strip()
            if not text:
                continue
            who = str(m.get("user_name") or "unknown")
            body = f"Channel: #{channel}\n{who}: {text}".strip()
            rows.append((str(uuid4()), body, seq + 1, seq + 1, seq, "slack_message", agent_id))
            seq += 1
        return rows

    body = render_unit_text(transcript)
    if not body:
        return rows
    rows.append((str(uuid4()), body, 1, 1, 0, "slack_turn_window", agent_id))
    return rows
