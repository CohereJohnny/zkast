"""Offline dreaming / memory evolution (per-agent, audited)."""

from __future__ import annotations

import json
import math
import re
from typing import Any

import structlog
from openai import AsyncOpenAI

from app.config import get_settings
from app.cohere_adapters import CohereEmbedder
from app.graphiti_factory import COHERE_COMPAT_BASE, resolve_cohere_api_key
from app.note_embedding_index import upsert_amem_embeddings_for_notes
from app.north_repo import finalize_dream_job, insert_dream_job, insert_dream_mutation
from app.notes_repo import (
    add_note_link,
    append_evolution_history,
    list_notes,
    patch_note_derivations,
)
from app.workspace_repo import fetch_pipeline_settings

logger = structlog.get_logger(__name__)


def _extract_json_object(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise
        return json.loads(m.group(0))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def run_dreaming_job(
    ctx: dict[str, Any],
    *,
    workspace_id: str,
    agent_id: str,
) -> None:
    """arq task: consolidate links + evolve derived fields for one agent."""
    database_url: str = ctx["database_url"]
    settings = get_settings()
    api_key = resolve_cohere_api_key(settings, workspace_id)
    if not api_key:
        raise RuntimeError("No Cohere API key for dreaming")

    pipe = fetch_pipeline_settings(database_url, workspace_id)
    model = str(pipe.get("large_model") or "command-a-plus-05-2026")
    embed_model = str(pipe.get("embed_model") or "embed-v4.0")

    job_id = insert_dream_job(database_url, workspace_id=workspace_id, agent_id=agent_id)
    stats: dict[str, Any] = {
        "pairs_considered": 0,
        "links_added": 0,
        "neighbors_updated": 0,
    }
    reindex_amem: set[str] = set()

    try:
        notes, _total = list_notes(
            database_url,
            workspace_id=workspace_id,
            agent_id=agent_id,
            limit=60,
            offset=0,
            sort="updated_at_desc",
        )
        if len(notes) < 2:
            finalize_dream_job(
                database_url,
                job_id=job_id,
                status="succeeded",
                stats={**stats, "message": "not_enough_notes"},
            )
            return

        embedder = CohereEmbedder(api_key=api_key, model=embed_model, embedding_dim=1536)
        texts = [f"{n.get('title','')}\n{n.get('body','')}"[:6000] for n in notes]
        vectors = await embedder.create_batch(texts)
        id_by_idx = [str(n["id"]) for n in notes]

        client = AsyncOpenAI(
            api_key=api_key,
            base_url=COHERE_COMPAT_BASE,
            timeout=120.0,
            max_retries=1,
        )

        for i, note in enumerate(notes):
            vec_i = vectors[i] if i < len(vectors) else None
            if not vec_i:
                continue
            scored: list[tuple[float, int]] = []
            for j, vec_j in enumerate(vectors):
                if i == j or not vec_j:
                    continue
                scored.append((_cosine(list(vec_i), list(vec_j)), j))
            scored.sort(reverse=True)
            neighbors = scored[:6]
            if not neighbors:
                continue

            neighbor_summaries = []
            for _sim, j in neighbors:
                nj = notes[j]
                neighbor_summaries.append(
                    {
                        "note_id": id_by_idx[j],
                        "title": nj.get("title"),
                        "body_preview": str(nj.get("body") or "")[:800],
                        "tags": nj.get("tags") or [],
                        "memory_context": nj.get("memory_context"),
                    }
                )

            focus = {
                "note_id": id_by_idx[i],
                "title": note.get("title"),
                "body_preview": str(note.get("body") or "")[:1200],
                "tags": note.get("tags") or [],
                "memory_context": note.get("memory_context"),
            }

            system = (
                "You perform conservative memory evolution for one agent scope. "
                "Given a focus note and neighbor summaries, output strict JSON with:\n"
                "{ \"should_link\": bool, \"link_target_note_id\": string|null, "
                "\"link_kind\": \"related\"|\"supports\"|\"extends\", "
                "\"link_reason\": string, \"neighbor_context_update\": string|null, "
                "\"neighbor_tag_additions\": string[] }\n"
                "Rules: never invent IDs outside the neighbor list + focus id; "
                "prefer no link if weak; neighbor_context_update applies only to the chosen link target."
            )
            user = json.dumps({"focus": focus, "neighbors": neighbor_summaries}, ensure_ascii=False)

            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or ""
            if not raw.strip():
                continue
            try:
                decision = _extract_json_object(raw)
            except json.JSONDecodeError:
                logger.warning("dreaming_bad_json", note_id=id_by_idx[i])
                continue

            stats["pairs_considered"] += 1
            if not decision.get("should_link"):
                continue

            target = str(decision.get("link_target_note_id") or "")
            if not target or target == id_by_idx[i]:
                continue
            if target not in id_by_idx:
                continue

            kind = str(decision.get("link_kind") or "related")
            if kind not in ("related", "supports", "extends", "refutes", "references"):
                kind = "related"

            try:
                add_note_link(
                    database_url,
                    workspace_id=workspace_id,
                    source_note_id=id_by_idx[i],
                    target_note_id=target,
                    kind=kind,
                    custom_label=None,
                    origin="generated",
                    link_reason=str(decision.get("link_reason") or "")[:2000] or None,
                    link_strength=float(decision.get("link_strength") or 1.0),
                )
                stats["links_added"] += 1
                reindex_amem.add(id_by_idx[i])
                reindex_amem.add(target)
                insert_dream_mutation(
                    database_url,
                    dream_job_id=job_id,
                    note_id=id_by_idx[i],
                    mutation_type="link_added",
                    payload={"target": target, "kind": kind},
                )
            except ValueError as exc:
                if "cross_agent" in str(exc):
                    logger.warning("dreaming_cross_agent_blocked", error=str(exc))
                continue

            nctx = decision.get("neighbor_context_update")
            tag_adds = [str(t).strip().lower() for t in (decision.get("neighbor_tag_additions") or []) if str(t).strip()]
            if nctx or tag_adds:
                tgt_note = next((x for x in notes if str(x["id"]) == target), None)
                merged_tags = list(dict.fromkeys([*(tgt_note.get("tags") or []), *tag_adds]))[:30] if tgt_note else tag_adds
                patch_note_derivations(
                    database_url,
                    workspace_id=workspace_id,
                    note_id=target,
                    memory_context=str(nctx)[:2000] if nctx else None,
                    tags=merged_tags if merged_tags else None,
                    mark_dreaming_touch=True,
                )
                append_evolution_history(
                    database_url,
                    workspace_id=workspace_id,
                    note_id=target,
                    entry={
                        "dream_job_id": job_id,
                        "source_note_id": id_by_idx[i],
                        "context": nctx,
                        "tags_added": tag_adds,
                    },
                )
                stats["neighbors_updated"] += 1
                reindex_amem.add(target)
                insert_dream_mutation(
                    database_url,
                    dream_job_id=job_id,
                    note_id=target,
                    mutation_type="neighbor_patch",
                    payload={"from": id_by_idx[i]},
                )

        if reindex_amem and api_key:
            await upsert_amem_embeddings_for_notes(
                api_key=api_key,
                database_url=database_url,
                workspace_id=workspace_id,
                note_ids=sorted(reindex_amem),
                agent_id=agent_id,
                embed_model=embed_model,
            )

        finalize_dream_job(database_url, job_id=job_id, status="succeeded", stats=stats)
    except Exception as exc:  # noqa: BLE001
        logger.exception("dreaming_job_failed", agent_id=agent_id, error=str(exc))
        finalize_dream_job(
            database_url,
            job_id=job_id,
            status="failed",
            stats=stats,
            failure_reason=str(exc)[:2000],
        )
        raise
