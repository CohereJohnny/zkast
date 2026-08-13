"""Tests for text / markdown / email ingest helpers."""

from __future__ import annotations

from app.text_ingest import (
    chunk_plain_text,
    detect_upload_kind,
    parse_eml_headers_and_body,
)


def test_detect_upload_kind_by_extension() -> None:
    assert detect_upload_kind("notes.txt", None)[0] == "text"
    assert detect_upload_kind("readme.md", "text/plain")[0] == "markdown"
    assert detect_upload_kind("msg.eml", None)[:2] == ("email", "message/rfc822")
    assert detect_upload_kind("doc.pdf", "application/pdf")[0] == "pdf"


def test_detect_upload_kind_rejects_unknown() -> None:
    try:
        detect_upload_kind("x.bin", "application/octet-stream")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert str(exc) == "unsupported_media_type"


def test_chunk_plain_text_splits_long_paragraphs() -> None:
    text = "word " * 400
    chunks = chunk_plain_text(text, max_chars=256)
    assert len(chunks) > 1
    assert all(len(c) <= 256 for c in chunks)


def test_parse_eml_headers_and_body_skips_attachments() -> None:
    raw = b"""From: alice@example.com
To: bob@example.com
Subject: Hello
Date: Mon, 1 Jan 2024 12:00:00 +0000
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="BOUND"

--BOUND
Content-Type: text/plain; charset="utf-8"

Body line one.

--BOUND
Content-Type: application/pdf; name="secret.pdf"
Content-Disposition: attachment; filename="secret.pdf"
Content-Transfer-Encoding: base64

JVBERi0xLjQK

--BOUND--
"""
    out = parse_eml_headers_and_body(raw)
    assert "From: alice@example.com" in out
    assert "Subject: Hello" in out
    assert "Body line one." in out
    assert "secret.pdf" not in out
    assert "JVBERi0" not in out
