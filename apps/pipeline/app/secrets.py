"""AES-256-GCM helpers for at-rest encryption (API keys in Sprint 2+)."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypt(master_key: bytes, plaintext: bytes) -> str:
    """Return URL-safe base64 payload: nonce (12) || ciphertext || tag."""
    if len(master_key) != 32:
        raise ValueError("master_key must be 32 bytes")
    aes = AESGCM(master_key)
    nonce = os.urandom(12)
    ciphertext = aes.encrypt(nonce, plaintext, associated_data=None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt(master_key: bytes, payload_b64: str) -> bytes:
    if len(master_key) != 32:
        raise ValueError("master_key must be 32 bytes")
    raw = base64.b64decode(payload_b64)
    if len(raw) < 13:
        raise ValueError("invalid payload")
    nonce, ciphertext = raw[:12], raw[12:]
    aes = AESGCM(master_key)
    return aes.decrypt(nonce, ciphertext, associated_data=None)
