"""Sprint A — North transcript → episode dry-run and agent provenance."""

from __future__ import annotations

from app.transcript_episodes import (
    build_episode_rows_from_transcript,
    count_north_episode_rows_from_conversation,
    north_conversation_activity_iso,
    north_conversation_preview_payload,
)


def test_count_north_episode_rows_zero_when_only_system_messages() -> None:
    conv = {
        "title": "T",
        "messages": [
            {"role": "system", "content": "You are a bot."},
        ],
    }
    assert (
        count_north_episode_rows_from_conversation(
            conv=conv,
            import_settings=None,
            north_metadata={"north_external_agent_id": "ext-1", "agent_display_name": "A"},
        )
        == 0
    )


def test_count_north_episode_rows_positive_for_user_assistant_turn() -> None:
    conv = {
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ],
    }
    n = count_north_episode_rows_from_conversation(
        conv=conv,
        import_settings=None,
        north_metadata={"north_external_agent_id": "ext-1", "agent_display_name": "Agent"},
    )
    assert n >= 1


def test_build_episode_rows_carry_agent_id() -> None:
    agent_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    conv = {"messages": [{"role": "user", "content": "Q"}, {"role": "assistant", "content": "A"}]}
    rows = build_episode_rows_from_transcript(
        workspace_id="11111111-1111-1111-1111-111111111111",
        document_id="22222222-2222-2222-2222-222222222222",
        ingestion_run_id="33333333-3333-3333-3333-333333333333",
        agent_id=agent_uuid,
        raw_transcript=conv,
        import_settings={"segmentation_mode": "message"},
        north_metadata={"north_external_agent_id": "ext", "agent_display_name": "N", "conversation_title": "C"},
    )
    assert rows
    for row in rows:
        # insert_episodes tuple: id, text, page_start, page_end, sequence, kind, agent_id
        assert row[6] == agent_uuid
        assert row[5] in ("north_message", "north_turn_window")


def test_north_conversation_preview_payload_caps_messages_and_excerpts() -> None:
    long_body = "x" * 800
    conv = {
        "title": "My chat",
        "messages": [
            {"role": "user", "content": "short"},
            {"role": "assistant", "content": long_body},
        ],
    }
    p = north_conversation_preview_payload(conv, max_messages=1, max_excerpt_chars=100)
    assert p["title"] == "My chat"
    assert p["message_count"] == 2
    assert p["preview_truncated"] is True
    assert len(p["messages"]) == 1
    assert p["messages"][0]["role"] == "user"
    assert p["messages"][0]["excerpt"] == "short"

    p2 = north_conversation_preview_payload(conv, max_messages=2, max_excerpt_chars=100)
    assert p2["preview_truncated"] is False
    assert p2["messages"][1]["excerpt"].endswith("…")
    assert len(p2["messages"][1]["excerpt"]) == 101


def test_north_conversation_activity_iso_from_updated_at_string() -> None:
    iso = north_conversation_activity_iso({"title": "T", "updated_at": "2024-06-01T12:34:56Z"})
    assert iso is not None
    assert "2024-06-01" in iso


def test_north_conversation_activity_iso_from_messages() -> None:
    iso = north_conversation_activity_iso(
        {
            "messages": [
                {"role": "user", "content": "a", "created_at": "2024-05-02T09:00:00+00:00"},
                {"role": "assistant", "content": "b", "created_at": "2024-05-02T10:00:00+00:00"},
            ]
        },
    )
    assert iso is not None
    assert "10:00" in iso


def test_north_conversation_activity_iso_none_when_empty() -> None:
    assert north_conversation_activity_iso({"messages": []}) is None
