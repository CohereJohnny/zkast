"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/feedback-provider";
import {
  RETRIEVAL_MODE_LABELS,
} from "@/components/chat-panel";
import {
  useChatStream,
  type CitationSource,
} from "@/lib/chat-stream";

/**
 * Sprint 6b — side-by-side comparison of retrieval strategies.
 *
 * The user types a question once; we POST it to three brand-new chat
 * sessions in parallel (one per retrieval mode) and render their
 * streaming answers in three columns. Each column shows the mode
 * label, the streaming answer, citation count, latency, and refusal
 * state so the user can directly contrast how Naive RAG, GraphRAG,
 * and Hybrid handle the same query.
 *
 * Architecture note: each column owns its own ephemeral session +
 * useChatStream subscription. State is local to this component so the
 * regular ChatPanel is unaffected.
 */

const MAX_INPUT_LEN = 4_000;

type CompareMode = "rag" | "graph" | "hybrid";

const COMPARE_MODES: CompareMode[] = ["rag", "graph", "hybrid"];

type ColumnState = {
  mode: CompareMode;
  sessionId: string | null;
  assistantMessageId: string | null;
  turnId: string | null;
  status: "idle" | "starting" | "streaming" | "complete" | "failed" | "refused";
  text: string;
  citations: Array<{
    text_start: number;
    text_end: number;
    text: string;
    sources: CitationSource[];
  }>;
  startedAt: number | null;
  completedAt: number | null;
  tokensIn: number | null;
  tokensOut: number | null;
  errorMessage: string | null;
};

function initialColumn(mode: CompareMode): ColumnState {
  return {
    mode,
    sessionId: null,
    assistantMessageId: null,
    turnId: null,
    status: "idle",
    text: "",
    citations: [],
    startedAt: null,
    completedAt: null,
    tokensIn: null,
    tokensOut: null,
    errorMessage: null,
  };
}

export function ChatComparePanel({ workspaceId }: { workspaceId: string }) {
  const toast = useToast();
  const [question, setQuestion] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [columns, setColumns] = useState<Record<CompareMode, ColumnState>>({
    rag: initialColumn("rag"),
    graph: initialColumn("graph"),
    hybrid: initialColumn("hybrid"),
  });

  const updateColumn = useCallback(
    (mode: CompareMode, delta: Partial<ColumnState>) => {
      setColumns((prev) => ({
        ...prev,
        [mode]: { ...prev[mode], ...delta },
      }));
    },
    [],
  );

  const reset = useCallback(() => {
    setColumns({
      rag: initialColumn("rag"),
      graph: initialColumn("graph"),
      hybrid: initialColumn("hybrid"),
    });
  }, []);

  const launchOne = useCallback(
    async (mode: CompareMode, q: string): Promise<void> => {
      updateColumn(mode, { status: "starting", startedAt: Date.now() });
      try {
        const sessRes = await fetch(
          `/api/v1/workspaces/${workspaceId}/chat-sessions`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              title: `Compare ${RETRIEVAL_MODE_LABELS[mode].label}`,
              model_settings: { retrieval_mode: mode },
              seed_message: q,
            }),
          },
        );
        const sessJson = (await sessRes.json()) as {
          session?: { id: string };
          first_turn?: {
            assistant_message?: { id: string };
            turn_id?: string;
          };
          error?: { message?: string };
        };
        if (!sessRes.ok || !sessJson.session || !sessJson.first_turn?.turn_id) {
          updateColumn(mode, {
            status: "failed",
            errorMessage:
              sessJson.error?.message ?? `HTTP ${sessRes.status}`,
            completedAt: Date.now(),
          });
          return;
        }
        updateColumn(mode, {
          sessionId: sessJson.session.id,
          assistantMessageId: sessJson.first_turn.assistant_message?.id ?? null,
          turnId: sessJson.first_turn.turn_id,
          status: "streaming",
        });
      } catch (err) {
        updateColumn(mode, {
          status: "failed",
          errorMessage: err instanceof Error ? err.message : "Network error",
          completedAt: Date.now(),
        });
      }
    },
    [workspaceId, updateColumn],
  );

  const submit = useCallback(async () => {
    const q = question.trim();
    if (!q || submitting) return;
    setSubmitting(true);
    reset();
    await Promise.all(COMPARE_MODES.map((m) => launchOne(m, q)));
    setSubmitting(false);
  }, [question, submitting, launchOne, reset]);

  return (
    <section
      aria-label="Compare retrieval strategies"
      // No ``max-w`` cap here: the side rails on the workspace shell
      // (Documents, Graph) are collapsible, and the Compare view should
      // reclaim that horizontal real-estate when either rail is folded
      // so the three answer columns aren't squeezed.
      className="flex w-full flex-col gap-3"
    >
      <header className="flex flex-col gap-1 border-b border-border pb-2">
        <h2 className="text-p font-medium text-foreground">
          Compare retrieval strategies
        </h2>
        <p className="text-caption text-muted-foreground">
          Submit one question and see how Naive RAG, GraphRAG, and Hybrid
          answer side by side. Each card streams its own answer; the
          retrieval mode is locked per column.
        </p>
      </header>

      <div className="flex flex-col gap-2 rounded-md border border-border bg-card/40 p-3">
        <label
          htmlFor="compare-question"
          className="text-caption font-medium text-muted-foreground"
        >
          Question
        </label>
        <textarea
          id="compare-question"
          value={question}
          onChange={(e) =>
            setQuestion(e.target.value.slice(0, MAX_INPUT_LEN))
          }
          rows={2}
          placeholder="e.g. How many Locations are mentioned in this workspace?"
          disabled={submitting}
          className="w-full resize-y rounded border border-input bg-card px-2 py-2 text-muted-foreground placeholder:text-muted-foreground/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        />
        <div className="flex items-center justify-between">
          <span className="text-caption text-muted-foreground">
            {question.length}/{MAX_INPUT_LEN}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={reset}
              disabled={submitting}
              className="cursor-pointer rounded border border-input px-3 py-1 text-caption text-muted-foreground transition-colors duration-150 hover:bg-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            >
              Clear
            </button>
            <button
              type="button"
              onClick={() => {
                void submit().catch((err) => {
                  toast({
                    variant: "error",
                    message: "Compare failed",
                    description:
                      err instanceof Error ? err.message : "Unknown error",
                  });
                });
              }}
              disabled={!question.trim() || submitting}
              className="cursor-pointer rounded-md bg-primary px-3 py-1 text-caption font-medium text-primary-foreground transition-colors duration-150 hover:bg-primary/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "Running…" : "Compare"}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        {COMPARE_MODES.map((mode) => (
          <CompareColumn
            key={mode}
            workspaceId={workspaceId}
            column={columns[mode]}
            onState={updateColumn}
          />
        ))}
      </div>
    </section>
  );
}

function CompareColumn({
  workspaceId,
  column,
  onState,
}: {
  workspaceId: string;
  column: ColumnState;
  onState: (mode: CompareMode, delta: Partial<ColumnState>) => void;
}) {
  const meta = RETRIEVAL_MODE_LABELS[column.mode];
  const startedAtRef = useRef<number | null>(column.startedAt);
  startedAtRef.current = column.startedAt;

  useChatStream(workspaceId, column.turnId, {
    onToken: ({ delta }) => {
      onState(column.mode, {
        status: "streaming",
        text: (column.text || "") + delta,
      });
    },
    onCitation: (c) => {
      onState(column.mode, {
        citations: [...column.citations, c],
      });
    },
    onMessageComplete: ({ finish_reason, tokens_in, tokens_out }) => {
      onState(column.mode, {
        status: finish_reason === "refused" ? "refused" : "complete",
        completedAt: Date.now(),
        tokensIn: tokens_in ?? null,
        tokensOut: tokens_out ?? null,
      });
    },
    onJobFailed: ({ reason }) => {
      onState(column.mode, {
        status: "failed",
        errorMessage: reason,
        completedAt: Date.now(),
      });
    },
    onJobCancelled: ({ reason }) => {
      onState(column.mode, {
        status: "failed",
        errorMessage: `Cancelled: ${reason}`,
        completedAt: Date.now(),
      });
    },
  });

  const latencyMs =
    column.startedAt && column.completedAt
      ? column.completedAt - column.startedAt
      : column.startedAt && column.status === "streaming"
        ? Date.now() - column.startedAt
        : null;

  const [tick, setTick] = useState(0);
  // Update once a second while streaming so the latency counter ticks.
  useEffect(() => {
    if (column.status !== "streaming") return;
    const id = window.setInterval(() => setTick((n) => n + 1), 500);
    return () => window.clearInterval(id);
  }, [column.status]);
  void tick;

  return (
    <article
      aria-label={`${meta.label} answer`}
      className="flex min-h-[260px] min-w-0 flex-col gap-2 rounded-md border border-border bg-background/60 p-3"
    >
      <header className="flex items-start justify-between">
        <div>
          <h3 className="text-caption font-semibold uppercase tracking-wider text-muted-foreground">
            {meta.label}
          </h3>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
            {meta.tagline}
          </p>
        </div>
        <StatusBadge status={column.status} />
      </header>
      <div className="min-h-0 flex-1 overflow-auto rounded border border-border/60 bg-card/40 p-2 text-p text-foreground whitespace-pre-wrap break-words">
        {column.status === "idle" ? (
          <p className="text-caption text-muted-foreground">
            Submit a question to see this strategy&rsquo;s answer.
          </p>
        ) : column.status === "starting" ? (
          <p className="text-caption text-muted-foreground">Starting session…</p>
        ) : column.status === "failed" ? (
          <p className="text-caption text-red-300">
            {column.errorMessage || "Failed."}
          </p>
        ) : column.status === "refused" ? (
          <p className="text-caption text-amber-100">
            {column.text || "Refused: no grounding context."}
          </p>
        ) : (
          <p>{column.text || "…"}</p>
        )}
      </div>
      <footer className="flex flex-wrap items-center gap-3 text-[10px] uppercase tracking-wider text-muted-foreground">
        <span>citations: {column.citations.length}</span>
        <span>
          latency:{" "}
          {latencyMs != null ? `${(latencyMs / 1000).toFixed(1)}s` : "—"}
        </span>
        <span>
          tokens:{" "}
          {column.tokensIn != null || column.tokensOut != null
            ? `${column.tokensIn ?? 0} / ${column.tokensOut ?? 0}`
            : "—"}
        </span>
      </footer>
    </article>
  );
}

function StatusBadge({ status }: { status: ColumnState["status"] }) {
  const map: Record<ColumnState["status"], { label: string; cls: string }> = {
    idle: { label: "Idle", cls: "text-muted-foreground bg-card" },
    starting: { label: "Starting", cls: "text-primary bg-primary/10" },
    streaming: {
      label: "Streaming",
      cls: "text-primary bg-primary/10",
    },
    complete: {
      label: "Complete",
      cls: "text-emerald-300 bg-emerald-500/10",
    },
    refused: {
      label: "Refused",
      cls: "text-amber-200 bg-amber-500/10",
    },
    failed: {
      label: "Failed",
      cls: "text-red-300 bg-red-500/10",
    },
  };
  const cfg = map[status];
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${cfg.cls}`}
    >
      {cfg.label}
    </span>
  );
}
