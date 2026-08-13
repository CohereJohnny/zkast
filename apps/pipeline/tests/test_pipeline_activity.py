"""Narrative activity helpers for the pipeline theater."""

from app.job_redis import narrative_log_for_theater
from app.tasks import _graph_batch_thought_label


def test_narrative_log_for_theater_promotes_synthesis():
    assert (
        narrative_log_for_theater("Synthesising notes from 12 chunks (max 50)")
        == "Synthesising notes from 12 chunks (max 50)"
    )


def test_narrative_log_for_theater_blocks_worker_noise():
    assert narrative_log_for_theater("generate_atomic_notes worker started") is None


def test_narrative_log_for_theater_episode_line():
    assert (
        narrative_log_for_theater("episode 2/5: +3 entities, +5 edges")
        == "Episode 2/5 — mapped 3 entities and 5 edges"
    )


def test_graph_batch_thought_label_with_samples():
    assert _graph_batch_thought_label(["Chevron", "MRP-227"], 4, 2) == "Spotted Chevron and MRP-227 (+2 more)"


def test_graph_batch_thought_label_single_name():
    assert _graph_batch_thought_label(["ASME Section XI"], 1, 0) == "Spotted ASME Section XI"


def test_graph_batch_thought_label_counts_only():
    assert _graph_batch_thought_label([], 3, 5) == "Wired 3 entities with 5 relationships"
