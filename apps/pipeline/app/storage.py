"""Local filesystem storage for uploaded PDFs."""

from __future__ import annotations

import hashlib
from pathlib import Path

import aiofiles
from fastapi import UploadFile


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def ensure_relative_uri(self, workspace_id: str, doc_id: str) -> str:
        return f"local://{workspace_id}/{doc_id}.pdf"

    def absolute_path(self, workspace_id: str, doc_id: str) -> Path:
        d = self.root / workspace_id
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{doc_id}.pdf"

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
    ) -> tuple[str, str, int]:
        """Stream upload to disk; rolling SHA-256. Validates %PDF magic on first chunk."""
        path = self.absolute_path(workspace_id, doc_id)
        hasher = hashlib.sha256()
        total = 0
        first_chunk = True
        async with aiofiles.open(path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                if first_chunk:
                    if not chunk.startswith(b"%PDF"):
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

        if total == 0:
            path.unlink(missing_ok=True)
            raise ValueError("empty_file")

        uri = self.ensure_relative_uri(workspace_id, doc_id)
        return uri, hasher.hexdigest(), total

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
