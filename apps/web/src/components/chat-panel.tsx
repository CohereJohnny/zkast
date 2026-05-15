"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import { ChatCitation } from "@/components/chat-citation";
import {
  ChatScopePicker,
  type ChatScopeValue,
} from "@/components/chat-scope-picker";
import { useToast } from "@/components/feedback-provider";
import {
  useChatStream,
  type CitationSource,
} from "@/lib/chat-stream";

/**
 * Sprint 6 — minimal grounded-chat panel.
 *
 * One active session per page. User types into the textarea, hits Send;
 * the panel POSTs to the messages endpoint, opens the SSE proxy, streams
 * tokens into the trailing assistant bubble, records citations as inline
 * superscripts. A Stop button (visible while streaming) cancels the turn
 * cooperatively.
 *
 * Full polish (Chat Home, drawer, regeneration, share visibility,
 * session list, message virtualization) is Sprint 7.
 */

type Citation = {
  text_start: number;
  text_end: number;
  text: string;
  sources: CitationSource[];
};

type Message = {
  id: string; // synthetic for pending/streaming; real for persisted
  role: "user" | "assistant";
  content: string;
  status: "complete" | "streaming" | "refused" | "failed" | "cancelled";
  citations: Citation[];
};

type SessionShape = {
  id: string;
  title: string;
  scope: Record<string, unknown>;
};

export type RetrievalMode =
  | "rag"
  | "raw_transcript"
  | "graph"
  | "hybrid"
  | "zettelkasten_notes"
  | "amem_lite";

const MAX_INPUT_LEN = 20_000;
const ARIA_LIVE_THROTTLE_MS = 150;

/**
 * Sprint 6b — labels for the retrieval-strategy selector. The copy is
 * verbatim from the user's principle that Naive RAG must use raw
 * document chunks only.
 */
export const RETRIEVAL_MODE_LABELS: Record<
  RetrievalMode,
  { label: string; tagline: string; helper: string }
> = {
  rag: {
    label: "Naive RAG",
    tagline: "Raw document chunks only",
    helper:
      "Embed the question and retrieve top-K original parsed PDF chunks. No zettelkasten notes, entities, or graph traversal.",
  },
  raw_transcript: {
    label: "Raw transcript",
    tagline: "Same as Naive RAG",
    helper: "Alias for Naive RAG — evaluates North transcript chunks under agent scope when configured.",
  },
  graph: {
    label: "GraphRAG",
    tagline: "Zettelkasten + graph context",
    helper:
      "Graphiti hybrid search across atomic notes, entities, and relationships plus a graph-shape summary.",
  },
  hybrid: {
    label: "Hybrid",
    tagline: "Traversal + supporting evidence",
    helper:
      "Deterministic typed-entity and multi-hop handlers for 'how many' / 'list all' / 'how is A related to B'; falls through to GraphRAG for vector questions.",
  },
  zettelkasten_notes: {
    label: "Zettel notes",
    tagline: "Vector over note bodies",
    helper: "Embeddings on title+body only (note_zettel index). Respects agent scope when set.",
  },
  amem_lite: {
    label: "A-MEM lite",
    tagline: "Vector over enriched notes",
    helper: "Embeddings include memory_context and memory_keywords after enrichment (note_amem index).",
  },
};

export function ChatPanel({ workspaceId }: { workspaceId: string }) {
  const toast = useToast();

  const [session, setSession] = useState<SessionShape | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [turnId, setTurnId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [scope, setScope] = useState<ChatScopeValue>({});
  // Sprint 6b — retrieval strategy selector. Defaults to ``graph`` so
  // behaviour matches Sprint 6. The selected mode is locked in when
  // the first message of a session is sent (it persists onto
  // ``chat_messages.retrieval_mode`` and ``chat_sessions.model_settings``).
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>("graph");

  // Track the currently-streaming assistant message id so token deltas
  // append to it.
  const streamingIdRef = useRef<string | null>(null);
  // Throttled aria-live buffer so screen readers don't get spammed.
  const announceBufRef = useRef("");
  const announceTimerRef = useRef<number | null>(null);
  const [announce, setAnnounce] = useState("");
  const bodyRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll on new message / token.
  useEffect(() => {
    const node = bodyRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [messages.length, announce]);

  const flushAnnounce = useCallback(() => {
    setAnnounce(announceBufRef.current);
    announceBufRef.current = "";
    announceTimerRef.current = null;
  }, []);

  const queueAnnounce = useCallback(
    (delta: string) => {
      announceBufRef.current += delta;
      if (announceTimerRef.current != null) return;
      announceTimerRef.current = window.setTimeout(
        flushAnnounce,
        ARIA_LIVE_THROTTLE_MS,
      );
    },
    [flushAnnounce],
  );

  useEffect(() => {
    return () => {
      if (announceTimerRef.current != null) {
        window.clearTimeout(announceTimerRef.current);
      }
    };
  }, []);

  // -------------------------------------------------------------------
  // SSE wiring
  // -------------------------------------------------------------------

  useChatStream(workspaceId, turnId, {
    onToken: ({ delta }) => {
      const id = streamingIdRef.current;
      if (!id) return;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id ? { ...m, content: m.content + delta, status: "streaming" } : m,
        ),
      );
      queueAnnounce(delta);
    },
    onCitation: (c) => {
      const id = streamingIdRef.current;
      if (!id) return;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id
            ? {
                ...m,
                citations: [...m.citations, c],
              }
            : m,
        ),
      );
    },
    onMessageComplete: ({ finish_reason }) => {
      const id = streamingIdRef.current;
      streamingIdRef.current = null;
      setSubmitting(false);
      setTurnId(null);
      if (!id) return;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === id
            ? {
                ...m,
                status:
                  finish_reason === "refused"
                    ? "refused"
                    : "complete",
              }
            : m,
        ),
      );
    },
    onJobFailed: ({ reason }) => {
      streamingIdRef.current = null;
      setSubmitting(false);
      setTurnId(null);
      setMessages((prev) =>
        prev.map((m) =>
          m.status === "streaming"
            ? { ...m, status: "failed", content: m.content || reason }
            : m,
        ),
      );
      toast({ variant: "error", message: "Chat turn failed", description: reason });
    },
    onJobCancelled: ({ reason }) => {
      streamingIdRef.current = null;
      setSubmitting(false);
      setTurnId(null);
      setMessages((prev) =>
        prev.map((m) =>
          m.status === "streaming" ? { ...m, status: "cancelled" } : m,
        ),
      );
      toast({
        variant: "info",
        message: "Chat turn cancelled",
        description: reason,
      });
    },
    onError: (err) => {
      // Transient EventSource hiccup; the browser retries — don't toast.
      // Surface only if we never got a terminal event.
      // eslint-disable-next-line no-console
      console.debug("chat-stream-error", err);
    },
  });

  // -------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------

  const ensureSession = useCallback(async (): Promise<SessionShape | null> => {
    if (session) return session;
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/chat-sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope,
          // Sprint 6b — persist the strategy on the session so every
          // turn the user submits in this session uses the same mode.
          model_settings: { retrieval_mode: retrievalMode },
        }),
      });
      const body = (await res.json()) as {
        session?: SessionShape;
        error?: { message?: string };
      };
      if (!res.ok || !body.session) {
        toast({
          variant: "error",
          message: "Could not create chat session",
          description: body.error?.message ?? `HTTP ${res.status}`,
        });
        return null;
      }
      setSession(body.session);
      return body.session;
    } catch (err) {
      toast({
        variant: "error",
        message: "Network error creating chat session",
        description: err instanceof Error ? err.message : "Unknown error",
      });
      return null;
    }
  }, [session, workspaceId, scope, retrievalMode, toast]);

  const submit = useCallback(
    async (e?: FormEvent) => {
      e?.preventDefault();
      const content = input.trim();
      if (!content || submitting) return;
      setSubmitting(true);
      const s = await ensureSession();
      if (!s) {
        setSubmitting(false);
        return;
      }

      // Optimistically render the user message + placeholder assistant
      // bubble; both are replaced by real ids once the server responds.
      const tmpUserId = `u-${Date.now()}`;
      const tmpAssistantId = `a-${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        {
          id: tmpUserId,
          role: "user",
          content,
          status: "complete",
          citations: [],
        },
        {
          id: tmpAssistantId,
          role: "assistant",
          content: "",
          status: "streaming",
          citations: [],
        },
      ]);
      setInput("");

      try {
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/chat-sessions/${s.id}/messages`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content }),
          },
        );
        const body = (await res.json()) as {
          user_message?: { id: string };
          assistant_message?: { id: string };
          turn_id?: string;
          error?: { message?: string };
        };
        if (!res.ok || !body.assistant_message || !body.turn_id) {
          toast({
            variant: "error",
            message: "Submit failed",
            description: body.error?.message ?? `HTTP ${res.status}`,
          });
          setMessages((prev) =>
            prev.map((m) =>
              m.id === tmpAssistantId
                ? { ...m, status: "failed" }
                : m,
            ),
          );
          setSubmitting(false);
          return;
        }

        // Replace placeholder ids with the real assistant id so SSE token
        // deltas append to the right bubble.
        const realAssistantId = body.assistant_message.id;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === tmpAssistantId ? { ...m, id: realAssistantId } : m,
          ),
        );
        streamingIdRef.current = realAssistantId;
        setTurnId(body.turn_id);
      } catch (err) {
        toast({
          variant: "error",
          message: "Network error",
          description: err instanceof Error ? err.message : "Unknown",
        });
        setMessages((prev) =>
          prev.map((m) =>
            m.id === tmpAssistantId ? { ...m, status: "failed" } : m,
          ),
        );
        setSubmitting(false);
      }
    },
    [input, submitting, ensureSession, workspaceId, toast],
  );

  const stop = useCallback(async () => {
    if (!turnId) return;
    try {
      await fetch(
        `/api/v1/workspaces/${workspaceId}/chat/turns/${turnId}/cancel`,
        { method: "POST" },
      );
    } catch (err) {
      toast({
        variant: "error",
        message: "Cancel request failed",
        description: err instanceof Error ? err.message : "Unknown",
      });
    }
  }, [turnId, workspaceId, toast]);

  // -------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------

  const hasMessages = messages.length > 0;

  return (
    <section
      aria-label="Grounded chat"
      className="mx-auto flex h-full w-full max-w-3xl flex-col"
    >
      <header className="flex flex-col gap-2 border-b border-border-subtle pb-2">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h1 className="text-body font-medium text-primary">
              {session?.title || "New chat"}
            </h1>
            <p className="text-caption text-muted">
              Grounded answers cite notes, entities, and source pages from this workspace.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setScopeOpen((o) => !o)}
            aria-expanded={scopeOpen}
            className="cursor-pointer rounded border border-border-strong px-2 py-1 text-caption text-secondary transition-colors duration-150 hover:bg-surface-raised focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
          >
            {scopeOpen ? "Hide scope" : "Scope"}
          </button>
        </div>
        <RetrievalModeSelector
          value={retrievalMode}
          onChange={setRetrievalMode}
          disabled={session !== null}
        />
      </header>

      {scopeOpen && !session ? (
        <div className="mt-3 rounded-md border border-border-subtle bg-surface/40 p-3">
          <ChatScopePicker
            workspaceId={workspaceId}
            value={scope}
            onChange={setScope}
          />
          <p className="mt-2 text-caption text-muted">
            Scope is locked in when the first message is sent.
          </p>
        </div>
      ) : null}

      <div
        ref={bodyRef}
        className="mt-3 flex-1 overflow-y-auto rounded-md border border-border-subtle bg-canvas px-3 py-3"
      >
        {!hasMessages ? (
          <p className="py-12 text-center text-caption text-muted">
            Ask a question about anything in this workspace. Answers cite notes and source pages.
          </p>
        ) : (
          <ul className="flex flex-col gap-4">
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} workspaceId={workspaceId} />
            ))}
          </ul>
        )}
      </div>

      <div className="sr-only" aria-live="polite" aria-atomic="false">
        {announce}
      </div>

      <form
        onSubmit={submit}
        className="mt-3 flex flex-col gap-2 border-t border-border-subtle pt-3"
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value.slice(0, MAX_INPUT_LEN))}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              void submit();
            }
          }}
          placeholder="Ask a question…"
          aria-label="Chat message"
          rows={2}
          disabled={submitting}
          className="w-full resize-y rounded border border-border-strong bg-surface px-2 py-2 text-secondary placeholder:text-muted/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary disabled:opacity-50"
        />
        <div className="flex items-center justify-between">
          <span className="text-caption text-muted">
            {input.length}/{MAX_INPUT_LEN} · Cmd-Enter to send
          </span>
          {submitting && turnId ? (
            <button
              type="button"
              onClick={() => void stop()}
              className="cursor-pointer rounded border border-semantic-danger/60 bg-semantic-danger/10 px-3 py-1 text-caption font-medium text-semantic-danger transition-colors duration-150 hover:bg-semantic-danger/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-semantic-danger"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!input.trim() || submitting}
              className="cursor-pointer rounded-md bg-accent-primary px-3 py-1 text-caption font-medium text-canvas transition-colors duration-150 hover:bg-accent-primary-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              Send
            </button>
          )}
        </div>
      </form>
    </section>
  );
}

function MessageBubble({
  message,
  workspaceId,
}: {
  message: Message;
  workspaceId: string;
}) {
  const isUser = message.role === "user";

  if (message.status === "refused") {
    return (
      <li>
        <div className="rounded-md border border-semantic-warning/40 bg-semantic-warning/10 px-3 py-2 text-caption text-amber-100">
          {message.content || "No grounding context found."}
        </div>
      </li>
    );
  }

  if (message.status === "failed") {
    return (
      <li>
        <div className="rounded-md border border-semantic-danger/40 bg-semantic-danger/10 px-3 py-2 text-caption text-red-200">
          Turn failed.
        </div>
      </li>
    );
  }

  return (
    <li className={isUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={
          isUser
            ? "max-w-[85%] rounded-md bg-surface-raised px-3 py-2 text-body text-primary"
            : "max-w-[95%] rounded-md border border-border-subtle bg-surface/40 px-3 py-3 text-body text-primary"
        }
      >
        <AssistantContent
          message={message}
          workspaceId={workspaceId}
          isUser={isUser}
        />
        {message.status === "streaming" && !isUser ? (
          <span className="ml-1 inline-block h-3 w-1 animate-pulse bg-accent-primary align-middle" />
        ) : null}
      </div>
    </li>
  );
}

function AssistantContent({
  message,
  workspaceId,
  isUser,
}: {
  message: Message;
  workspaceId: string;
  isUser: boolean;
}) {
  // Render content with inline citation chips at the right positions.
  // For user messages, just render the text. For assistant messages,
  // splice citations in order of text_start.
  const parts = useMemo(() => {
    if (isUser || message.citations.length === 0) {
      return [{ kind: "text" as const, text: message.content, key: "all" }];
    }
    const sorted = [...message.citations].sort(
      (a, b) => a.text_start - b.text_start,
    );
    const out: Array<
      | { kind: "text"; text: string; key: string }
      | {
          kind: "citation";
          index: number;
          sources: CitationSource[];
          key: string;
        }
    > = [];
    let cursor = 0;
    sorted.forEach((c, i) => {
      const safeEnd = Math.min(c.text_end, message.content.length);
      const safeStart = Math.max(0, Math.min(c.text_start, safeEnd));
      if (safeStart > cursor) {
        out.push({
          kind: "text",
          text: message.content.slice(cursor, safeStart),
          key: `t-${cursor}-${safeStart}`,
        });
      }
      out.push({
        kind: "text",
        text: message.content.slice(safeStart, safeEnd),
        key: `c-text-${i}`,
      });
      out.push({
        kind: "citation",
        index: i,
        sources: c.sources,
        key: `c-mark-${i}`,
      });
      cursor = safeEnd;
    });
    if (cursor < message.content.length) {
      out.push({
        kind: "text",
        text: message.content.slice(cursor),
        key: `t-tail-${cursor}`,
      });
    }
    return out;
  }, [message.citations, message.content, isUser]);

  return (
    <span className="whitespace-pre-wrap break-words">
      {parts.map((p) =>
        p.kind === "text" ? (
          <span key={p.key}>{p.text}</span>
        ) : (
          <ChatCitation
            key={p.key}
            index={p.index}
            sources={p.sources}
            workspaceId={workspaceId}
          />
        ),
      )}
    </span>
  );
}

function RetrievalModeSelector({
  value,
  onChange,
  disabled,
}: {
  value: RetrievalMode;
  onChange: (mode: RetrievalMode) => void;
  disabled: boolean;
}) {
  const modes: RetrievalMode[] = [
    "rag",
    "raw_transcript",
    "graph",
    "hybrid",
    "zettelkasten_notes",
    "amem_lite",
  ];
  const meta = RETRIEVAL_MODE_LABELS[value];
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-caption text-muted">
        Retrieval strategy
        <select
          className="mt-1 w-full rounded-md border border-border-strong bg-surface px-2 py-1.5 text-body text-primary"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value as RetrievalMode)}
        >
          {modes.map((m) => (
            <option key={m} value={m}>
              {RETRIEVAL_MODE_LABELS[m].label} — {RETRIEVAL_MODE_LABELS[m].tagline}
            </option>
          ))}
        </select>
      </label>
      <p className="text-caption text-muted">
        {meta.helper}
        {disabled ? " — locked for this session; start a new chat to switch." : ""}
      </p>
    </div>
  );
}
