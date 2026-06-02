"""Composable pipeline stages: pluggable Extractor / GraphStore / Retriever plugins
and the Pipeline Configuration model that composes them.

See specs/openspecs/composable-eval-harness.md. This package is additive: it
introduces the stage abstraction + registry + configuration model. Routing the
runtime extraction/retrieval through it (so the current pipeline becomes the
seeded ``builtin-default`` configuration) lands in a subsequent slice.
"""
