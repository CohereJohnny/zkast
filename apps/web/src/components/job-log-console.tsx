"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useToast } from "@/components/feedback-provider";
import { emitGraphInvalidated } from "@/lib/graph-events";
import {
  type ActiveJob,
  useActiveJobs,
  useJobEvents,
} from "@/lib/job-events";

/**
 * Live, collapsible "build log" drawer.
 *
 * - Subscribes (one `EventSource` per active job) to
 *   `/api/v1/jobs/{jobId}/events`. The server replays the last ~200 events
 *   from the Redis Stream before tailing live pub/sub messages, so opening
 *   the drawer feels instant.
 * - Auto-dismisses jobs from the active-jobs context on `job_completed` /
 *   `job_failed`.
 * - Cross-wires `metric` events whose name implies graph mutation
 *   (`entity_count`, `edge_count`, `note_count`) into `emitGraphInvalidated`
 *   so the canvas refetches without polling.
 * - Persists collapsed/expanded state via localStorage to mirror the
 *   documents-panel pattern.
 */

const STORAGE_KEY = "zkast.workspace.logConsole.open";
const MAX_LINES = 1500;

type Level = "info" | "warning" | "error";

type LogLine = {
  id: string;
  ts: number;
  jobId: string;
  type: string;
  level: Level;
  stage: string;
  message: string;
  data?: Record<string, unknown>;
};

type ServerEvent = {
  type?: string;
  level?: Level;
  stage?: string;
  message?: string;
  reason?: string;
  status?: string;
  percent?: number;
  current?: number;
  total?: number;
  name?: string;
  value?: number | string;
  data?: Record<string, unknown>;
};

const LEVEL_CLASS: Record<Level, string> = {
  info: "text-secondary",
  warning: "text-amber-200",
  error: "text-red-300",
};

const STAGE_LABEL: Record<string, string> = {
  parsing: "Parse",
  generating_notes: "Notes",
  extracting_graph: "Graph",
  building_graph: "Graph",
};

function classifyLevel(ev: ServerEvent): Level {
  if (ev.level === "warning" || ev.level === "error") return ev.level;
  if (ev.type === "job_failed" || ev.type === "warning") return "warning";
  if (ev.type === "log" && (ev.level === "info" || !ev.level)) return "info";
  return "info";
}

function eventToMessage(ev: ServerEvent): string {
  if (ev.type === "log" && ev.message) return ev.message;
  if (ev.type === "metric" && ev.name) {
    return `${ev.name}=${ev.value}`;
  }
  if (ev.type === "stage_started") return `Stage started: ${ev.stage}`;
  if (ev.type === "stage_completed") return `Stage completed: ${ev.stage}`;
  if (ev.type === "stage_progress") {
    if (typeof ev.percent === "number") {
      return `Progress ${ev.percent}%${
        ev.current != null && ev.total != null ? ` (${ev.current}/${ev.total})` : ""
      }`;
    }
    return "Progress update";
  }
  if (ev.type === "job_completed") return `Job completed (${ev.status ?? "ok"})`;
  if (ev.type === "job_failed") return `Job failed: ${ev.reason ?? "unknown"}`;
  if (ev.type === "warning" && ev.message) return ev.message;
  return ev.type ?? "event";
}

function StageBadge({ stage }: { stage: string }) {
  const label = STAGE_LABEL[stage] ?? stage;
  return (
    <span className="rounded border border-border-subtle bg-surface-raised px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-muted">
      {label}
    </span>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className={`h-4 w-4 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

function ConsoleIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3.75 4.5h16.5a1.5 1.5 0 0 1 1.5 1.5v12a1.5 1.5 0 0 1-1.5 1.5H3.75a1.5 1.5 0 0 1-1.5-1.5V6a1.5 1.5 0 0 1 1.5-1.5Z" />
      <path d="m7 9 3 3-3 3M13.5 15h4" />
    </svg>
  );
}

function useEventSource(
  jobId: string,
  onEvent: (ev: ServerEvent) => void,
  onTerminal: () => void,
) {
  useEffect(() => {
    const url = `/api/v1/jobs/${encodeURIComponent(jobId)}/events`;
    const es = new EventSource(url);
    let closed = false;
    es.onmessage = (msg) => {
      if (closed) return;
      try {
        const ev = JSON.parse(msg.data) as ServerEvent;
        onEvent(ev);
        if (ev.type === "job_completed" || ev.type === "job_failed") {
          closed = true;
          es.close();
          onTerminal();
        }
      } catch {
        /* ignore malformed */
      }
    };
    es.onerror = () => {
      es.close();
    };
    return () => {
      closed = true;
      es.close();
    };
  }, [jobId, onEvent, onTerminal]);
}

function JobSubscription({
  job,
  onEvent,
  onTerminal,
}: {
  job: ActiveJob;
  onEvent: (jobId: string, ev: ServerEvent) => void;
  onTerminal: (jobId: string) => void;
}) {
  const event = useCallback(
    (ev: ServerEvent) => onEvent(job.jobId, ev),
    [job.jobId, onEvent],
  );
  const terminal = useCallback(() => onTerminal(job.jobId), [job.jobId, onTerminal]);
  useEventSource(job.jobId, event, terminal);
  return null;
}

export function JobLogConsole() {
  const jobs = useActiveJobs();
  const { unregisterActiveJob } = useJobEvents();
  const toast = useToast();

  const [open, setOpen] = useState(false);
  const [follow, setFollow] = useState(true);
  const [levelFilter, setLevelFilter] = useState<"all" | Level>("all");
  const [jobFilter, setJobFilter] = useState<string>("all");
  const [lines, setLines] = useState<LogLine[]>([]);
  const lineCounter = useRef(0);
  const bodyRef = useRef<HTMLDivElement | null>(null);

  // Hydrate collapsed state.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "1") setOpen(true);
    } catch {
      /* ignore */
    }
  }, []);

  const persistOpen = useCallback((next: boolean) => {
    setOpen(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, []);

  const handleEvent = useCallback(
    (jobId: string, ev: ServerEvent) => {
      lineCounter.current += 1;
      const line: LogLine = {
        id: `${jobId}-${lineCounter.current}`,
        ts: Date.now(),
        jobId,
        type: ev.type ?? "event",
        level: classifyLevel(ev),
        stage: ev.stage ?? "",
        message: eventToMessage(ev),
        data: ev.data,
      };
      setLines((prev) => {
        const next = [...prev, line];
        return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
      });
      if (ev.type === "metric" && ev.name) {
        if (["entity_count", "edge_count", "note_count"].includes(ev.name)) {
          emitGraphInvalidated();
        }
      }
    },
    [],
  );

  const handleTerminal = useCallback(
    (jobId: string) => {
      // Small grace so the closing event has time to render.
      window.setTimeout(() => unregisterActiveJob(jobId), 1500);
    },
    [unregisterActiveJob],
  );

  // Auto-scroll to bottom when following.
  useEffect(() => {
    if (!open || !follow) return;
    const node = bodyRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [open, follow, lines.length]);

  // Pause follow when user scrolls up.
  const onScroll = useCallback(() => {
    const node = bodyRef.current;
    if (!node) return;
    const atBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 32;
    if (!atBottom && follow) setFollow(false);
  }, [follow]);

  const filteredLines = useMemo(() => {
    return lines.filter((l) => {
      if (jobFilter !== "all" && l.jobId !== jobFilter) return false;
      if (levelFilter !== "all" && l.level !== levelFilter) return false;
      return true;
    });
  }, [lines, jobFilter, levelFilter]);

  const copyLog = useCallback(async () => {
    const text = filteredLines
      .map((l) => {
        const t = new Date(l.ts).toISOString();
        return `${t}\t${l.jobId.slice(0, 8)}\t${l.level.toUpperCase()}\t${l.stage || "-"}\t${l.message}`;
      })
      .join("\n");
    try {
      await navigator.clipboard.writeText(text);
      toast({ variant: "success", message: "Log copied to clipboard" });
    } catch {
      toast({ variant: "error", message: "Clipboard write failed" });
    }
  }, [filteredLines, toast]);

  const clearLog = useCallback(() => {
    setLines([]);
  }, []);

  const hasJobs = jobs.length > 0;
  const lineCountLabel = `${filteredLines.length}${
    filteredLines.length !== lines.length ? `/${lines.length}` : ""
  } lines`;

  return (
    <div
      aria-label="Ingestion log console"
      className="pointer-events-none fixed inset-x-0 bottom-0 z-[35] flex flex-col items-end px-4 pb-2 sm:px-6"
    >
      {jobs.map((j) => (
        <JobSubscription
          key={j.jobId}
          job={j}
          onEvent={handleEvent}
          onTerminal={handleTerminal}
        />
      ))}
      <div
        className={`pointer-events-auto mx-auto w-full max-w-5xl rounded-t-lg border border-b-0 border-border-strong bg-surface-overlay shadow-modal backdrop-blur transition-all duration-200 ${
          open ? "" : "max-w-md"
        }`}
      >
        <button
          type="button"
          onClick={() => persistOpen(!open)}
          aria-expanded={open}
          className="flex w-full items-center gap-2 rounded-t-lg px-3 py-2 text-caption text-secondary transition-colors duration-150 hover:bg-surface-raised focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary focus-visible:ring-inset"
        >
          <ConsoleIcon />
          <span className="font-medium">Pipeline log</span>
          <span className="text-muted">
            {hasJobs ? `${jobs.length} active` : "idle"}
          </span>
          <span className="ml-auto text-muted">{lineCountLabel}</span>
          <ChevronIcon open={open} />
        </button>
        {open ? (
          <div className="flex flex-col gap-2 border-t border-border-subtle px-3 py-2">
            <div className="flex flex-wrap items-center gap-2 text-caption text-muted">
              <label className="flex items-center gap-1">
                <span>Level</span>
                <select
                  value={levelFilter}
                  onChange={(e) =>
                    setLevelFilter(e.target.value as "all" | Level)
                  }
                  className="rounded border border-border-strong bg-canvas px-1.5 py-0.5 text-secondary"
                >
                  <option value="all">All</option>
                  <option value="info">Info</option>
                  <option value="warning">Warning</option>
                  <option value="error">Error</option>
                </select>
              </label>
              <label className="flex items-center gap-1">
                <span>Job</span>
                <select
                  value={jobFilter}
                  onChange={(e) => setJobFilter(e.target.value)}
                  className="max-w-[16ch] truncate rounded border border-border-strong bg-canvas px-1.5 py-0.5 text-secondary"
                >
                  <option value="all">All</option>
                  {jobs.map((j) => (
                    <option key={j.jobId} value={j.jobId}>
                      {j.jobId.slice(0, 8)}
                      {j.kind ? ` · ${j.kind.replace(/_/g, " ")}` : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={follow}
                  onChange={(e) => setFollow(e.target.checked)}
                />
                Follow tail
              </label>
              <button
                type="button"
                onClick={() => void copyLog()}
                className="ml-auto rounded border border-border-strong px-2 py-0.5 text-secondary transition-colors duration-150 hover:bg-surface-raised"
              >
                Copy
              </button>
              <button
                type="button"
                onClick={clearLog}
                className="rounded border border-border-strong px-2 py-0.5 text-secondary transition-colors duration-150 hover:bg-surface-raised"
              >
                Clear
              </button>
            </div>
            <div
              ref={bodyRef}
              onScroll={onScroll}
              className="h-48 overflow-y-auto rounded-md border border-border-subtle bg-canvas px-2 py-1 font-mono text-[12px] leading-relaxed"
              role="log"
              aria-live="polite"
            >
              {filteredLines.length === 0 ? (
                <p className="text-muted">
                  {hasJobs
                    ? "Waiting for events…"
                    : "No active jobs. Upload a PDF or retry from a stage to see live progress here."}
                </p>
              ) : (
                filteredLines.map((l) => (
                  <p key={l.id} className="whitespace-pre-wrap break-words">
                    <span className="text-muted">
                      {new Date(l.ts).toLocaleTimeString()}
                    </span>{" "}
                    <span className="text-muted">{l.jobId.slice(0, 8)}</span>{" "}
                    <StageBadge stage={l.stage || "-"} />{" "}
                    <span className={LEVEL_CLASS[l.level]}>{l.message}</span>
                  </p>
                ))
              )}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
