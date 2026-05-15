"""North eval retrieval mode wiring."""

from types import SimpleNamespace

from app.eval import runner as eval_runner


def test_retrieval_module_aliases() -> None:
    raw = eval_runner._retrieval_module("raw_transcript")
    assert raw is eval_runner.chat_retrieval_raw

    z = eval_runner._retrieval_module("zettelkasten_notes")
    assert isinstance(z, SimpleNamespace)
    assert z.retrieve.__name__ == "retrieve_zettel"

    a = eval_runner._retrieval_module("amem_lite")
    assert isinstance(a, SimpleNamespace)
    assert a.retrieve.__name__ == "retrieve_amem"
