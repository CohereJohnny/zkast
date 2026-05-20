"""North conversation import status and ingest-content hashing."""

from __future__ import annotations

from app.north_checksum import (
    north_conversation_content_checksum,
    north_ingest_content_hash,
    stamp_cache_payload_ingest_hash,
    text_content_hash,
)
from app.north_import_status import (
    agent_import_digest,
    attach_import_status_to_conversations,
    resolve_import_state,
    sync_status_from_import_state,
)


def _sample_messages() -> dict:
    return {"messages": [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]}


def test_ingest_hash_ignores_json_wrapper_noise() -> None:
    """List-shaped vs dict-shaped transcript with same messages → same ingest hash."""
    settings: dict = {}
    meta = {"conversation_title": "T", "agent_display_name": "A", "north_external_agent_id": "x"}
    full = _sample_messages()
    listed = full["messages"]
    h_full = north_ingest_content_hash(full, import_settings=settings, north_metadata=meta)
    h_list = north_ingest_content_hash(listed, import_settings=settings, north_metadata=meta)
    assert h_full == h_list
    assert h_full != north_conversation_content_checksum({"messages": listed, "id": "extra"})


def test_raw_json_checksum_differs_for_wrapper() -> None:
    a = {"id": "c1", "messages": [{"role": "user", "content": "x"}]}
    b = {"messages": [{"role": "user", "content": "x"}]}
    assert north_conversation_content_checksum(a) != north_conversation_content_checksum(b)


def test_sync_status_merges_imported_and_current() -> None:
    assert sync_status_from_import_state("imported") == "synced"
    assert sync_status_from_import_state("current") == "synced"
    assert sync_status_from_import_state("stale") == "outdated"


def test_resolve_not_imported() -> None:
    st = resolve_import_state(doc=None, cache_payload=_sample_messages())
    assert st["import_state"] == "not_imported"
    assert st["sync_status"] == "not_synced"


def test_resolve_current_on_matching_ingest_hash() -> None:
    settings: dict = {}
    meta = {"conversation_title": "T", "agent_display_name": "A", "north_external_agent_id": "x"}
    payload = stamp_cache_payload_ingest_hash(
        _sample_messages(),
        import_settings=settings,
        north_metadata=meta,
        full_transcript=True,
    )
    ingest = north_ingest_content_hash(payload, import_settings=settings, north_metadata=meta)
    doc = {"id": "d1", "checksum": "storage", "status": "ready", "north_metadata": {"ingest_content_hash": ingest}}
    st = resolve_import_state(
        doc=doc,
        cache_payload=payload,
        import_settings=settings,
        north_metadata=meta,
    )
    assert st["import_state"] == "current"
    assert st["sync_status"] == "synced"


def test_resolve_imported_not_stale_for_list_cache() -> None:
    """List refresh payload with messages must not false-positive as stale."""
    settings: dict = {}
    meta = {"conversation_title": "T", "agent_display_name": "A", "north_external_agent_id": "x"}
    ingest = north_ingest_content_hash(_sample_messages(), import_settings=settings, north_metadata=meta)
    doc = {"id": "d1", "checksum": "x", "status": "ready", "north_metadata": {"ingest_content_hash": ingest}}
    list_row = {"id": "c1", "title": "T", "messages": _sample_messages()["messages"]}
    st = resolve_import_state(doc=doc, cache_payload=list_row, import_settings=settings, north_metadata=meta)
    assert st["import_state"] == "imported"


def test_resolve_stale_only_when_stamped_cache_differs() -> None:
    settings: dict = {}
    meta = {"conversation_title": "T", "agent_display_name": "A", "north_external_agent_id": "x"}
    old = stamp_cache_payload_ingest_hash(
        {"messages": [{"role": "user", "content": "old"}]},
        import_settings=settings,
        north_metadata=meta,
        full_transcript=True,
    )
    ingest_old = north_ingest_content_hash(old, import_settings=settings, north_metadata=meta)
    doc = {"id": "d1", "checksum": "x", "status": "ready", "north_metadata": {"ingest_content_hash": ingest_old}}
    new = stamp_cache_payload_ingest_hash(
        {"messages": [{"role": "user", "content": "new"}]},
        import_settings=settings,
        north_metadata=meta,
        full_transcript=True,
    )
    st = resolve_import_state(doc=doc, cache_payload=new, import_settings=settings, north_metadata=meta)
    assert st["import_state"] == "stale"


def test_resolve_processing() -> None:
    doc = {"id": "d1", "checksum": "x", "status": "parsing", "north_metadata": {"ingest_content_hash": "abc"}}
    st = resolve_import_state(doc=doc, cache_payload=_sample_messages())
    assert st["import_state"] == "processing"


def test_attach_import_status_batch() -> None:
    settings: dict = {}
    meta = {"conversation_title": "T", "agent_display_name": "A", "north_external_agent_id": "x"}
    payload = stamp_cache_payload_ingest_hash(
        _sample_messages(),
        import_settings=settings,
        north_metadata=meta,
        full_transcript=True,
    )
    ingest = north_ingest_content_hash(payload, import_settings=settings, north_metadata=meta)
    items = [{"north_conversation_id": "c1", "payload": payload, "fetched_at": None}]
    docs = {"c1": {"id": "d1", "checksum": "x", "status": "ready", "north_metadata": {"ingest_content_hash": ingest}}}
    mem = {"c1": {"notes": 2, "amem_embeddings": 2, "document_status": "ready", "ingest_digest": "abc"}}
    out = attach_import_status_to_conversations(
        items,
        docs,
        import_settings=settings,
        agent_north_metadata=meta,
        memory_stats_by_conversation=mem,
    )
    assert out[0]["import_state"] == "current"
    assert out[0]["sync_status"] == "synced"
    assert out[0]["memory"]["notes"] == 2


def test_text_content_hash() -> None:
    assert text_content_hash("a") == text_content_hash("a")
    assert text_content_hash("a") != text_content_hash("b")


def test_agent_import_digest_prefers_ingest_hash() -> None:
    docs = {
        "c1": {"checksum": "raw", "north_metadata": {"ingest_content_hash": "ingest-a"}},
        "c2": {"checksum": "raw2", "north_metadata": {}},
    }
    d = agent_import_digest(docs)
    assert d is not None
    assert len(d) == 64
