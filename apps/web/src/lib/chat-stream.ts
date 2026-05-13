"use client";

import { useEffect, useRef } from "react";

/**
 * Sprint 6 — typed SSE client for a single chat turn.
 *
 * Opens an `EventSource` against
 * `/api/v1/workspaces/{ws}/chat/turns/{id}?workspaceId=...` and dispatches
 * each parsed `data:` payload to a typed callback based on `type`. The
 * upstream pipeline emits seven event kinds (see
 * [`specs/apis.md`](../../../specs/apis.md) `GET /jobs/{id}/events`):
 *
 *   retrieval_started, retrieval_complete, token, citation,
 *   message_complete, job_failed, job_cancelled
 *
 * The hook auto-closes the EventSource on any terminal event so callers
 * don't have to track state. EventSource handles reconnect natively;
 * `Last-Event-ID` is sent by the browser on reconnect when set by the
 * server's `id:` field. We don't currently set `id:` server-side, so
 * reconnect just resumes from the live pub/sub channel (the Sprint 5b
 * Redis Stream replay covers the gap on initial connect).
 */

export type CitationSource = {
  kind: string;
  id?: string;
  document_id?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  excerpt?: string;
};

export type ChatStreamCallbacks = {
  onRetrievalStarted?: (e: { query_text: string }) => void;
  onRetrievalComplete?: (e: {
    retrieval_record_id: string;
    total_candidates: number;
    kept: number;
    truncated: boolean;
  }) => void;
  onToken?: (e: { delta: string }) => void;
  onCitation?: (e: {
    text_start: number;
    text_end: number;
    text: string;
    sources: CitationSource[];
  }) => void;
  onMessageComplete?: (e: {
    message_id: string;
    finish_reason: string;
    tokens_in?: number | null;
    tokens_out?: number | null;
    citation_count?: number;
  }) => void;
  onJobFailed?: (e: { reason: string; stage?: string }) => void;
  onJobCancelled?: (e: { reason: string }) => void;
  onError?: (err: unknown) => void;
};

type ServerEvent = {
  type?: string;
  [key: string]: unknown;
};

/**
 * Subscribe to a chat turn's SSE stream.
 *
 * Pass ``null`` for ``turnId`` to disable (e.g., before the user submits
 * the first message). The hook tears down on unmount or when ``turnId``
 * changes.
 */
export function useChatStream(
  workspaceId: string,
  turnId: string | null,
  callbacks: ChatStreamCallbacks,
): void {
  // Hold the latest callbacks in a ref so re-renders that change the
  // callbacks identity don't tear down the EventSource.
  const cbRef = useRef(callbacks);
  cbRef.current = callbacks;

  useEffect(() => {
    if (!turnId || !workspaceId) return;
    const url = `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/chat/turns/${encodeURIComponent(turnId)}?workspaceId=${encodeURIComponent(workspaceId)}`;
    const es = new EventSource(url);
    let closed = false;

    const closeOnce = () => {
      if (closed) return;
      closed = true;
      es.close();
    };

    es.onmessage = (msg) => {
      if (closed) return;
      let ev: ServerEvent;
      try {
        ev = JSON.parse(msg.data) as ServerEvent;
      } catch {
        return;
      }
      const t = ev.type;
      try {
        switch (t) {
          case "retrieval_started":
            cbRef.current.onRetrievalStarted?.({
              query_text: String(ev.query_text ?? ""),
            });
            break;
          case "retrieval_complete":
            cbRef.current.onRetrievalComplete?.({
              retrieval_record_id: String(ev.retrieval_record_id ?? ""),
              total_candidates: Number(ev.total_candidates ?? 0),
              kept: Number(ev.kept ?? 0),
              truncated: Boolean(ev.truncated),
            });
            break;
          case "token":
            cbRef.current.onToken?.({ delta: String(ev.delta ?? "") });
            break;
          case "citation":
            cbRef.current.onCitation?.({
              text_start: Number(ev.text_start ?? 0),
              text_end: Number(ev.text_end ?? 0),
              text: String(ev.text ?? ""),
              sources: Array.isArray(ev.sources)
                ? (ev.sources as CitationSource[])
                : [],
            });
            break;
          case "message_complete":
            cbRef.current.onMessageComplete?.({
              message_id: String(ev.message_id ?? ""),
              finish_reason: String(ev.finish_reason ?? "complete"),
              tokens_in:
                typeof ev.tokens_in === "number" ? ev.tokens_in : null,
              tokens_out:
                typeof ev.tokens_out === "number" ? ev.tokens_out : null,
              citation_count:
                typeof ev.citation_count === "number"
                  ? ev.citation_count
                  : undefined,
            });
            closeOnce();
            break;
          case "job_failed":
            cbRef.current.onJobFailed?.({
              reason: String(ev.reason ?? "unknown"),
              stage: typeof ev.stage === "string" ? ev.stage : undefined,
            });
            closeOnce();
            break;
          case "job_cancelled":
            cbRef.current.onJobCancelled?.({
              reason: String(ev.reason ?? "cancelled"),
            });
            closeOnce();
            break;
          default:
            // Other event types (`log`, `metric`, `stage_*`) are visible
            // in the JobLogConsole drawer; we ignore them here so the
            // chat UI stays focused on the canonical seven.
            break;
        }
      } catch (err) {
        cbRef.current.onError?.(err);
      }
    };

    es.onerror = (err) => {
      // EventSource attempts reconnect automatically. Only surface the
      // error once we've actually closed (terminal-event path); for
      // transient blips we let the browser retry.
      if (closed) return;
      cbRef.current.onError?.(err);
    };

    return () => {
      closeOnce();
    };
  }, [workspaceId, turnId]);
}
