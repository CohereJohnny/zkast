"""Local filesystem storage for uploaded documents (PDF, text, markdown, email)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from app.text_ingest import (
    detect_upload_kind,
    validate_eml_payload,
    validate_text_payload,
)

_EXT_BY_KIND = {
    "pdf": "pdf",
    "text": "txt",
    "markdown": "md",
    "email": "eml",
}


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def ensure_relative_uri(self, workspace_id: str, doc_id: str, *, ext: str = "pdf") -> str:
        return f"local://{workspace_id}/{doc_id}.{ext}"

    def absolute_path(self, workspace_id: str, doc_id: str, *, ext: str = "pdf") -> Path:
        d = self.root / workspace_id
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{doc_id}.{ext}"

    @staticmethod
    def absolute_path_from_uri(storage_uri: str, root: str | Path) -> Path:
        if not storage_uri.startswith("local://"):
            raise ValueError(f"unsupported storage_uri scheme: {storage_uri!r}")
        rel = storage_uri.removeprefix("local://")
        return Path(root) / rel

    async def write_upload(
        self,
        workspace_id: str,
        doc_id: str,
        file: UploadFile,
        *,
        max_bytes: int,
        source_kind: str | None = None,
        mime_type: str | None = None,
        ext: str | None = None,
    ) -> tuple[str, str, int, str, str]:
        """Stream upload to disk; rolling SHA-256.

        Returns ``(uri, checksum, byte_size, source_kind, mime_type)``.
        """
        if source_kind is None or mime_type is None or ext is None:
            source_kind, mime_type, ext = detect_upload_kind(file.filename, file.content_type)
        else:
            ext = ext or _EXT_BY_KIND.get(source_kind, "bin")

        path = self.absolute_path(workspace_id, doc_id, ext=ext)
        hasher = hashlib.sha256()
        total = 0
        first_chunk = True
        buf = bytearray()
        async with aiofiles.open(path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                if first_chunk:
                    if source_kind == "pdf" and not chunk.startswith(b"%PDF"):
                        path.unlink(missing_ok=True)
                        raise ValueError("not_pdf")
                    first_chunk = False
                total += len(chunk)
                if total > max_bytes:
                    await out.flush()
                    path.unlink(missing_ok=True)
                    raise ValueError("too_large")
                hasher.update(chunk)
                await out.write(chunk)
                if source_kind in ("text", "markdown", "email") and total <= 2_000_000:
                    buf.extend(chunk)

        if total == 0:
            path.unlink(missing_ok=True)
            raise ValueError("empty_file")

        if source_kind in ("text", "markdown"):
            try:
                validate_text_payload(bytes(buf) if buf else path.read_bytes())
            except ValueError:
                path.unlink(missing_ok=True)
                raise
        elif source_kind == "email":
            try:
                validate_eml_payload(bytes(buf) if buf else path.read_bytes())
            except ValueError:
                path.unlink(missing_ok=True)
                raise

        uri = self.ensure_relative_uri(workspace_id, doc_id, ext=ext)
        return uri, hasher.hexdigest(), total, source_kind, mime_type

    def ensure_relative_uri_north_json(self, workspace_id: str, doc_id: str) -> str:
        """URI for a North transcript snapshot stored as JSON on disk."""
        return f"local://{workspace_id}/{doc_id}.north.json"

    def absolute_path_north_json(self, workspace_id: str, doc_id: str) -> Path:
        d = self.root / workspace_id
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{doc_id}.north.json"

    async def write_north_transcript_json(
        self,
        workspace_id: str,
        doc_id: str,
        payload: bytes,
        *,
        max_bytes: int,
    ) -> tuple[str, str, int]:
        """Persist transcript JSON; rolling SHA-256 checksum (not PDF magic)."""
        if len(payload) > max_bytes:
            raise ValueError("too_large")
        if not payload:
            raise ValueError("empty_file")

        path = self.absolute_path_north_json(workspace_id, doc_id)
        hasher = hashlib.sha256()
        hasher.update(payload)
        async with aiofiles.open(path, "wb") as out:
            await out.write(payload)

        uri = self.ensure_relative_uri_north_json(workspace_id, doc_id)
        return uri, hasher.hexdigest(), len(payload)
