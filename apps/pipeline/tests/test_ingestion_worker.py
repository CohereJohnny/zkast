"""Optional end-to-end parse (requires Postgres + Redis + ZKAST_INGESTION_SMOKE=1)."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

import fitz
import pytest
import redis.asyncio as aioredis

from app.documents_repo import fetch_document, insert_document, insert_ingestion_run
from app.tasks import parse_document

DEFAULT_WS = "00000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(
    os.environ.get("ZKAST_INGESTION_SMOKE") != "1" or not os.environ.get("DATABASE_URL"),
    reason="Set ZKAST_INGESTION_SMOKE=1 and DATABASE_URL for compose-backed smoke test",
)


@pytest.mark.asyncio
async def test_parse_document_direct_smoke(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZKAST_STORAGE_ROOT", str(tmp_path))
    from app.config import Settings

    settings = Settings()

    doc_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    path = Path(tmp_path) / DEFAULT_WS
    path.mkdir(parents=True, exist_ok=True)
    pdf_path = path / f"{doc_id}.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "smoke episode")
    doc.save(pdf_path)
    doc.close()

    raw = pdf_path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    uri = f"local://{DEFAULT_WS}/{doc_id}.pdf"

    insert_document(
        settings.database_url,
        document_id=doc_id,
        workspace_id=DEFAULT_WS,
        original_filename="smoke.pdf",
        mime_type="application/pdf",
        byte_size=len(raw),
        storage_uri=uri,
        checksum=checksum,
        replaces_document_id=None,
        status="queued",
    )
    insert_ingestion_run(
        settings.database_url,
        run_id=run_id,
        document_id=doc_id,
        status="running",
        pipeline_version=settings.pipeline_version,
        llm_provider="cohere",
        llm_model_small="x",
        llm_model_large="y",
        stats={},
    )

    redis = await aioredis.from_url(settings.redis_url, decode_responses=True)
    ctx = {
        "redis": redis,
        "database_url": settings.database_url,
        "zkast_storage_root": str(tmp_path),
    }

    await parse_document(
        ctx,
        workspace_id=DEFAULT_WS,
        document_id=doc_id,
        ingestion_run_id=run_id,
        job_id=job_id,
    )

    row = fetch_document(settings.database_url, workspace_id=DEFAULT_WS, document_id=doc_id)
    assert row is not None
    assert row["status"] == "ready"
    assert row["page_count"] == 1

    await redis.aclose()
