"""Agent memory space graph naming."""

from app.memory_space import memory_space_graph_name


def test_global_graph_name_is_workspace_id() -> None:
    ws = "550e8400-e29b-41d4-a716-446655440000"
    assert memory_space_graph_name(ws, None) == ws
    assert memory_space_graph_name(ws, "") == ws


def test_agent_graph_name_is_scoped() -> None:
    ws = "550e8400-e29b-41d4-a716-446655440000"
    aid = "660e8400-e29b-41d4-a716-446655440001"
    name = memory_space_graph_name(ws, aid)
    assert name.startswith(ws)
    assert aid.replace("-", "_") in name or aid in name
