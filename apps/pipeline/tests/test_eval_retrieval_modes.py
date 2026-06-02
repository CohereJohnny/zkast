"""North eval retrieval mode wiring."""

from types import SimpleNamespace

from app import chat_retrieval_raw
from app.eval.adapters import memory_system_for_mode, retrieval_module


def test_retrieval_module_aliases() -> None:
    # retrieval_module now resolves through the shared stage registry and returns
    # an object exposing the resolved `.retrieve` callable for every mode.
    raw = retrieval_module("raw_transcript")
    assert isinstance(raw, SimpleNamespace)
    assert raw.retrieve is chat_retrieval_raw.retrieve

    z = retrieval_module("zettelkasten_notes")
    assert isinstance(z, SimpleNamespace)
    assert z.retrieve.__name__ == "retrieve_zettel"

    a = retrieval_module("amem_lite")
    assert isinstance(a, SimpleNamespace)
    assert a.retrieve.__name__ == "retrieve_amem"

    assert memory_system_for_mode("amem_lite") == "amem"
    assert memory_system_for_mode("rag") == "raw"
