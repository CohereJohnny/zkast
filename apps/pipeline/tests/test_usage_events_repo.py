"""Usage events persistence."""

from app.usage_events_repo import insert_usage_event, VALID_SOURCES


def test_valid_sources() -> None:
    assert "chat" in VALID_SOURCES
    assert "ingestion" in VALID_SOURCES
