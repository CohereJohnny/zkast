"""North agent repo — import_settings persistence on sync."""

from __future__ import annotations

import uuid

import psycopg
import pytest

from app.north_repo import upsert_north_agent
from tests.db_helpers import delete_test_north_agent, get_database_url

DEFAULT_WS = "00000000-0000-4000-8000-000000000003"

pytestmark = pytest.mark.skipif(get_database_url() is None, reason="DATABASE_URL not set")


def test_upsert_north_agent_preserves_import_settings_on_sync() -> None:
    db = get_database_url()
    assert db
    agent_id = str(uuid.uuid4())
    ext_id = f"test-import-settings-{agent_id[:8]}"
    saved_settings = {"user_messages_only": True, "include_roles": ["user"]}

    try:
        row = upsert_north_agent(
            db,
            workspace_id=DEFAULT_WS,
            external_agent_id=ext_id,
            display_name="Import settings agent",
            import_settings=saved_settings,
        )
        agent_id = str(row["id"])

        synced = upsert_north_agent(
            db,
            workspace_id=DEFAULT_WS,
            external_agent_id=ext_id,
            display_name="Import settings agent (renamed)",
        )
        assert synced["display_name"] == "Import settings agent (renamed)"
        assert synced["import_settings"] == saved_settings

        with psycopg.connect(db) as conn:
            db_row = conn.execute(
                """
                SELECT import_settings
                FROM north_agents
                WHERE id = %s::uuid AND workspace_id = %s::uuid
                """,
                (agent_id, DEFAULT_WS),
            ).fetchone()
        assert db_row is not None
        assert db_row[0] == saved_settings
    finally:
        delete_test_north_agent(db, workspace_id=DEFAULT_WS, agent_id=agent_id)
