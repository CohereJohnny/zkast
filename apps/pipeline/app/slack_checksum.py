"""Content checksums for Slack conversation units (import dedup)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.slack_transcript import render_unit_text


def slack_unit_content_checksum(transcript: dict[str, Any]) -> str:
    """SHA-256 over the normalized unit transcript JSON.

    Used as ``documents.checksum`` so an unchanged unit re-imports idempotently
    and a changed thread (e.g. a new reply) produces a distinct document.
    """
    raw = json.dumps(transcript, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def slack_unit_ingest_hash(transcript: dict[str, Any]) -> str:
    """SHA-256 over the rendered episode body — stable across wrapper changes."""
    body = render_unit_text(transcript)
    return hashlib.sha256(body.encode("utf-8")).hexdigest() if body else ""
