"""Stage-plugin contracts + the Pipeline Configuration model.

A Pipeline Configuration is a FIXED LINEAR chain (Parse -> Extract -> Store ->
Retrieve) where each stage is fulfilled by a registered plugin. Configurations
are versioned and content-hashed so a comparison/eval result can be pinned to
the exact composition that produced it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StageKind(str, Enum):
    PARSE = "parse"
    EXTRACT = "extract"
    STORE = "store"
    RETRIEVE = "retrieve"


@dataclass(frozen=True)
class StagePlugin:
    """A selectable implementation for one pipeline stage.

    ``module``/``attr`` are optional lazy-resolution hints for plugins that wrap
    an existing callable (e.g. a retrieval strategy's ``retrieve`` coroutine);
    ``strategy`` is the stable string recorded on results for retrievers.
    ``implemented`` marks plugins that are registered but not yet built.
    """

    id: str
    kind: StageKind
    label: str
    description: str = ""
    module: str | None = None
    attr: str | None = None
    strategy: str | None = None
    implemented: bool = True


def compute_content_hash(normalized: dict[str, Any]) -> str:
    """Deterministic SHA-256 over the normalized composition."""
    blob = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass
class PipelineConfiguration:
    """A named composition of stage choices."""

    name: str
    extractor: str
    graph_store: str
    retrieval_strategy: str
    ontology_version: str | None = None
    provider: str = "cohere_compat"
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    is_builtin: bool = False
    version: int = 1

    def normalized(self) -> dict[str, Any]:
        """The composition fields that define the content hash (identity)."""
        return {
            "extractor": self.extractor,
            "graph_store": self.graph_store,
            "retrieval_strategy": self.retrieval_strategy,
            "ontology_version": self.ontology_version,
            "provider": self.provider,
            "params": self.params or {},
        }

    @property
    def content_hash(self) -> str:
        return compute_content_hash(self.normalized())

    def to_doc(self) -> dict[str, Any]:
        """Portable representation (YAML/JSON export shape)."""
        doc = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "is_builtin": self.is_builtin,
            **self.normalized(),
        }
        return doc

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> "PipelineConfiguration":
        return cls(
            name=str(doc["name"]),
            description=str(doc.get("description") or ""),
            version=int(doc.get("version") or 1),
            is_builtin=bool(doc.get("is_builtin") or False),
            extractor=str(doc["extractor"]),
            graph_store=str(doc["graph_store"]),
            retrieval_strategy=str(doc["retrieval_strategy"]),
            ontology_version=doc.get("ontology_version"),
            provider=str(doc.get("provider") or "cohere_compat"),
            params=dict(doc.get("params") or {}),
        )
