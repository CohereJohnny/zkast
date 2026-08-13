"""LocalStorage upload hashing."""

from __future__ import annotations

import hashlib
from io import BytesIO

import fitz
import pytest
from starlette.datastructures import UploadFile

from app.storage import LocalStorage


def _pdf_bytes() -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "fixture")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.mark.asyncio
async def test_storage_write_checksum(tmp_path) -> None:
    raw = _pdf_bytes()
    expected = hashlib.sha256(raw).hexdigest()
    storage = LocalStorage(str(tmp_path))
    ws = "00000000-0000-4000-8000-000000000002"
    doc_id = "00000000-0000-4000-8000-000000000099"
    buf = BytesIO(raw)
    uf = UploadFile(file=buf, filename="t.pdf")
    uri, checksum, size, kind, mime = await storage.write_upload(
        ws, doc_id, uf, max_bytes=10_000_000
    )
    assert uri == f"local://{ws}/{doc_id}.pdf"
    assert checksum == expected
    assert size == len(raw)
    assert kind == "pdf"
    assert mime == "application/pdf"
    path = storage.absolute_path(ws, doc_id)
    assert path.is_file()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


@pytest.mark.asyncio
async def test_storage_rejects_non_pdf(tmp_path) -> None:
    storage = LocalStorage(str(tmp_path))
    buf = BytesIO(b"not a pdf")
    uf = UploadFile(file=buf, filename="x.pdf")
    with pytest.raises(ValueError, match="not_pdf"):
        await storage.write_upload("ws", "doc", uf, max_bytes=1000)


@pytest.mark.asyncio
async def test_storage_write_text(tmp_path) -> None:
    raw = b"hello collection\n"
    storage = LocalStorage(str(tmp_path))
    ws = "00000000-0000-4000-8000-000000000002"
    doc_id = "00000000-0000-4000-8000-000000000098"
    uf = UploadFile(file=BytesIO(raw), filename="notes.txt", headers={"content-type": "text/plain"})
    uri, checksum, size, kind, mime = await storage.write_upload(
        ws, doc_id, uf, max_bytes=10_000_000
    )
    assert uri.endswith(".txt")
    assert kind == "text"
    assert mime == "text/plain"
    assert checksum == hashlib.sha256(raw).hexdigest()
    assert size == len(raw)
