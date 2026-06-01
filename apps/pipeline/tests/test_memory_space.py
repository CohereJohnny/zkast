"""Agent memory space graph naming."""

from app.memory_space import memory_space_graph_name


def test_global_graph_name_sanitizes_workspace_uuid() -> None:
    ws = "550e8400-e29b-41d4-a716-446655440000"
    name = memory_space_graph_name(ws, None)
    assert "-" not in name
    assert name == "550e8400_e29b_41d4_a716_446655440000"


def test_agent_graph_name_is_scoped_and_redisearch_safe() -> None:
    ws = "550e8400-e29b-41d4-a716-446655440000"
    aid = "660e8400-e29b-41d4-a716-446655440001"
    name = memory_space_graph_name(ws, aid)
    assert "-" not in name
    assert name.endswith("_a_660e8400_e29b_41d4_a716_446655440001")
    assert memory_space_graph_name(ws, "") == memory_space_graph_name(ws, None)
