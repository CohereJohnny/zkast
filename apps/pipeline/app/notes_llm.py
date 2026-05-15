"""LLM-backed atomic note generation (Cohere OpenAI-compat).

Sprint 5b changes:
- Streaming mode (``stream=True``) reports token progress via the optional
  ``progress_callback``; the caller emits ``tokens_consumed`` metric events
  for the streaming console drawer.
- Explicit ``timeout=120.0`` and ``max_retries=1`` so a wedged Cohere call
  fails fast instead of silently retrying for ~30 minutes against the
  default OpenAI SDK settings.
- ``streaming`` arg is a runtime feature flag (default ``True``); set
  ``pipeline_settings.notes_llm_streaming = false`` to revert if Cohere's
  stream impl misbehaves on a given model.

Sprint 5b polish (BUG-009): Cohere's streaming endpoint occasionally yields
zero content chunks while still returning HTTP 200, leaving us with an
empty buffer and a ``JSONDecodeError: Expecting value: line 1 column 1
(char 0)``. We now retry once with ``stream=False`` before bubbling so a
brittle stream doesn't fail the whole notes stage.
"""

from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable

import structlog
from openai import AsyncOpenAI

from app.graphiti_factory import COHERE_COMPAT_BASE

logger = structlog.get_logger(__name__)


SYSTEM_PROMPT = """You are a Zettelkasten librarian. Given numbered source chunks from a PDF, produce atomic notes.
Rules:
- One idea per note (atomicity).
- Each note must cite which chunk indices (0-based) support it via source_chunk_indices array.
- Respect max_notes hard limit.
- Output strict JSON only: {"notes":[{"title":"...","body":"markdown","tags":["..."],"source_chunk_indices":[0]}],"suggested_links":[{"from":0,"to":1,"kind":"related","link_reason":"why"}]}
- suggested_links reference indices into the notes array you output (0-based).
- kind must be one of: related, supports, refutes, extends, references.
- link_reason is optional but recommended when the relationship is non-obvious.
"""


def _extract_json_object(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise
        return json.loads(m.group(0))


async def generate_notes_from_episodes(
    *,
    api_key: str,
    model: str,
    episodes: list[dict[str, Any]],
    max_notes: int,
    streaming: bool = True,
    progress_callback: Callable[[int], Awaitable[None]] | None = None,
    warning_callback: Callable[[str, dict[str, Any] | None], Awaitable[None]]
    | None = None,
    timeout_s: float = 120.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Synthesize notes from episodes.

    Returns ``(notes_payload, suggested_links)`` where notes have
    ``title``, ``body``, ``tags``, ``source_episode_ids`` (caller fills the
    final IDs).

    ``warning_callback`` (optional) lets the caller fan operationally
    interesting warnings (empty-stream fallback, JSON parse retry) out
    to the JobLogConsole drawer in addition to the worker's stderr.
    """
    if not episodes:
        return [], []

    chunks_lines = []
    id_by_index: list[str] = []
    for i, ep in enumerate(episodes):
        id_by_index.append(str(ep["id"]))
        preview = (ep.get("text") or "")[:6000]
        chunks_lines.append(f"[{i}] pages {ep.get('page_start')}-{ep.get('page_end')}: {preview}")

    user_content = (
        f"max_notes={max_notes}\n\n"
        + "\n\n".join(chunks_lines)
        + "\n\nRespond with JSON only."
    )

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=COHERE_COMPAT_BASE,
        timeout=timeout_s,
        max_retries=1,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    async def _non_streaming_call() -> str:
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content or ""

    async def _streaming_call() -> str:
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
            stream=True,
        )
        buf: list[str] = []
        token_count = 0
        last_progress_at = 0
        async for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content
            except (AttributeError, IndexError):
                delta = None
            if not delta:
                continue
            buf.append(delta)
            # Approximate token count via whitespace splits — cheap and
            # close enough for a progress meter.
            token_count += max(1, len(delta.split()))
            if progress_callback and token_count - last_progress_at >= 50:
                last_progress_at = token_count
                try:
                    await progress_callback(token_count)
                except Exception as cb_exc:  # noqa: BLE001
                    logger.warning("notes_llm_progress_cb_failed", error=str(cb_exc))
        if progress_callback and token_count > last_progress_at:
            try:
                await progress_callback(token_count)
            except Exception:  # noqa: BLE001
                pass
        return "".join(buf)

    raw_text: str = ""
    used_streaming = streaming
    try:
        if streaming:
            raw_text = await _streaming_call()
            # BUG-009 — Cohere's stream sometimes completes with zero
            # content chunks. Detect the empty / unparseable response and
            # retry once non-streaming before giving up.
            if not raw_text.strip():
                logger.warning(
                    "notes_llm_empty_stream_fallback_to_nonstreaming",
                    episodes=len(episodes),
                )
                if warning_callback:
                    try:
                        await warning_callback(
                            (
                                "Notes LLM stream returned no content; "
                                "retrying with stream=False"
                            ),
                            {"episodes": len(episodes), "reason": "empty_stream"},
                        )
                    except Exception:  # noqa: BLE001
                        pass
                used_streaming = False
                raw_text = await _non_streaming_call()
        else:
            raw_text = await _non_streaming_call()
    except Exception as exc:
        logger.warning(
            "notes_llm_call_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            streaming=used_streaming,
        )
        raise

    if not raw_text.strip():
        # Both paths produced an empty body. Surface a real error message —
        # tasks.py already wraps this in ``_describe_exception`` for the UI.
        raise RuntimeError(
            "Cohere returned an empty notes response (streaming="
            f"{used_streaming}); check API key, quota, or model name."
        )

    try:
        data = _extract_json_object(raw_text)
    except json.JSONDecodeError as exc:
        if used_streaming:
            # Streamed body was non-JSON (rare, but observed). Retry once
            # without streaming, which uses Cohere's batched JSON path and
            # is reliable for the ``response_format=json_object`` mode.
            logger.warning(
                "notes_llm_stream_unparseable_fallback_to_nonstreaming",
                error=str(exc),
                raw_preview=raw_text[:200],
            )
            if warning_callback:
                try:
                    await warning_callback(
                        (
                            "Notes LLM stream returned non-JSON; "
                            "retrying with stream=False"
                        ),
                        {"error": str(exc)[:200], "reason": "unparseable_stream"},
                    )
                except Exception:  # noqa: BLE001
                    pass
            raw_text = await _non_streaming_call()
            data = _extract_json_object(raw_text)
        else:
            raise
    raw_notes = list(data.get("notes") or [])[:max_notes]
    links = list(data.get("suggested_links") or [])

    out_notes: list[dict[str, Any]] = []
    for n in raw_notes:
        title = str(n.get("title") or "Untitled")[:200]
        body = str(n.get("body") or "")[:10000]
        tags = [str(t).strip().lower() for t in (n.get("tags") or []) if str(t).strip()][:20]
        idxs = [int(x) for x in (n.get("source_chunk_indices") or []) if 0 <= int(x) < len(id_by_index)]
        ep_ids = [id_by_index[i] for i in sorted(set(idxs))]
        if not ep_ids:
            continue
        out_notes.append({"title": title, "body": body, "tags": tags, "source_episode_ids": ep_ids})

    out_links: list[dict[str, Any]] = []
    for ln in links:
        try:
            fr = int(ln.get("from"))
            to = int(ln.get("to"))
            kind = str(ln.get("kind") or "related")
            if kind not in ("related", "supports", "refutes", "extends", "references"):
                kind = "related"
            if 0 <= fr < len(out_notes) and 0 <= to < len(out_notes) and fr != to:
                out_links.append(
                    {
                        "from": fr,
                        "to": to,
                        "kind": kind,
                        "link_reason": str(ln.get("link_reason") or ln.get("reason") or "").strip() or None,
                    }
                )
        except (TypeError, ValueError):
            continue

    return out_notes, out_links
