"""Tests for secrets helpers."""

from __future__ import annotations

import os

from app.secrets import decrypt, encrypt


def test_aes_gcm_roundtrip() -> None:
    key = os.urandom(32)
    plain = b"zkast-secret-test"
    blob = encrypt(key, plain)
    assert decrypt(key, blob) == plain
