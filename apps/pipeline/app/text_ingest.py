"""Parse text / markdown / email uploads into episode chunk rows."""

from __future__ import annotations

import email
import re
from email import policy
from email.message import Message
from typing import Iterable
from uuid import uuid4

# Matches tasks.chunk_page_text style: synthetic page 1 for non-PDF sources.
DEFAULT_MAX_CHARS = 2048


def detect_upload_kind(filename: str | None, content_type: str | None) -> tuple[str, str, str]:
    """Return ``(source_kind, mime_type, extension)`` for an upload file.

    Raises ``ValueError`` with a short code when the type is unsupported.
    """
    name = (filename or "").strip().lower()
    ctype = (content_type or "").split(";")[0].strip().lower()
    ext = ""
    if "." in name:
        ext = name.rsplit(".", 1)[-1]

    # Prefer filename extension when present (browsers often send text/plain for .md).
    if ext == "pdf":
        return ("pdf", "application/pdf", "pdf")
    if ext == "txt":
        return ("text", "text/plain", "txt")
    if ext in ("md", "markdown"):
        return ("markdown", "text/markdown", "md")
    if ext == "eml":
        return ("email", "message/rfc822", "eml")

    if ctype == "application/pdf":
        return ("pdf", "application/pdf", "pdf")
    if ctype in ("text/markdown", "text/x-markdown"):
        return ("markdown", "text/markdown", "md")
    if ctype == "text/plain":
        return ("text", "text/plain", "txt")
    if ctype in ("message/rfc822", "application/eml"):
        return ("email", "message/rfc822", "eml")
    raise ValueError("unsupported_media_type")


def chunk_plain_text(text: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Split UTF-8 text into overlapping-ish chunks by paragraph then size."""
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return []
    max_chars = max(256, int(max_chars))
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", cleaned) if p.strip()]
    if not paragraphs:
        paragraphs = [cleaned]

    chunks: list[str] = []
    buf = ""

    def flush_oversized(s: str) -> None:
        for i in range(0, len(s), max_chars):
            piece = s[i : i + max_chars]
            if piece:
                chunks.append(piece)

    for para in paragraphs:
        if len(para) > max_chars:
            if buf:
                flush_oversized(buf) if len(buf) > max_chars else chunks.append(buf)
                buf = ""
            flush_oversized(para)
            continue
        candidate = f"{buf}\n\n{para}".strip() if buf else para
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                if len(buf) > max_chars:
                    flush_oversized(buf)
                else:
                    chunks.append(buf)
            buf = para
    if buf:
        if len(buf) > max_chars:
            flush_oversized(buf)
        else:
            chunks.append(buf)
    return chunks


def _walk_text_parts(msg: Message) -> str:
    """Prefer text/plain body; fall back to stripped HTML; skip attachments."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            ctype = (part.get_content_type() or "").lower()
            if ctype == "text/plain":
                try:
                    plain_parts.append(part.get_content())
                except Exception:  # noqa: BLE001
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        plain_parts.append(payload.decode("utf-8", errors="replace"))
            elif ctype == "text/html":
                try:
                    html_parts.append(part.get_content())
                except Exception:  # noqa: BLE001
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        html_parts.append(payload.decode("utf-8", errors="replace"))
    else:
        ctype = (msg.get_content_type() or "").lower()
        try:
            body = msg.get_content()
        except Exception:  # noqa: BLE001
            payload = msg.get_payload(decode=True)
            body = (
                payload.decode("utf-8", errors="replace")
                if isinstance(payload, bytes)
                else str(msg.get_payload() or "")
            )
        if ctype == "text/html":
            html_parts.append(str(body))
        else:
            plain_parts.append(str(body))

    if plain_parts:
        return "\n\n".join(p.strip() for p in plain_parts if p and str(p).strip())
    if html_parts:
        return _strip_html("\n\n".join(html_parts))
    return ""


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_eml_headers_and_body(raw: bytes | str) -> str:
    """Extract From/To/Cc/Subject/Date + body text; attachments ignored."""
    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8", errors="replace")
    else:
        raw_bytes = raw
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)
    headers: list[str] = []
    for key in ("From", "To", "Cc", "Subject", "Date"):
        val = msg.get(key)
        if val:
            headers.append(f"{key}: {val}")
    body = _walk_text_parts(msg)
    if headers and body:
        return "\n".join(headers) + "\n\n" + body
    if headers:
        return "\n".join(headers)
    return body


def episode_rows_for_text(
    text: str,
    *,
    kind: str,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[tuple[str, str, int, int, int, str, str | None]]:
    """Build insert_episodes row tuples: (id, text, page_start, page_end, seq, kind, agent_id)."""
    chunks = chunk_plain_text(text, max_chars=max_chars)
    rows: list[tuple[str, str, int, int, int, str, str | None]] = []
    for i, chunk in enumerate(chunks):
        rows.append((str(uuid4()), chunk, 1, 1, i, kind, None))
    return rows


def decode_utf8_bytes(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def validate_text_payload(data: bytes) -> None:
    if not data:
        raise ValueError("empty_file")
    # Reject obvious binary (NUL bytes) for text/md.
    if b"\x00" in data[:8192]:
        raise ValueError("not_text")


def validate_eml_payload(data: bytes) -> None:
    if not data:
        raise ValueError("empty_file")
    try:
        email.message_from_bytes(data, policy=policy.default)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("not_eml") from exc
