"""Arq queue names.

Interactive grounded-chat turns run on a dedicated queue so they are never
stuck behind bulk ingestion (PDF/Slack/North parse → notes → graph) jobs on the
default queue. A separate worker process consumes this queue.
"""

from __future__ import annotations

# arq's default queue is ``arq:queue`` (ingestion, dreaming, wiki, imports).
CHAT_QUEUE_NAME = "arq:queue:chat"

# MS GraphRAG batch indexing runs on a dedicated graphrag-worker (its own image
# with graphrag + openai 2.x) consuming this queue, isolated from the main
# pipeline's openai 1.x deps.
GRAPHRAG_QUEUE_NAME = "arq:queue:graphrag"
