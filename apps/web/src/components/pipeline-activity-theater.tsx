"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { type ActiveJob, useActiveJobs, useJobEvents } from "@/lib/job-events";
import { emitGraphLiveDelta, parseGraphDeltaFromActivityData } from "@/lib/graph-live-delta";
import { emitPipelineActivity } from "@/lib/pipeline-activity";
import { type JobStreamEvent, useJobStream } from "@/lib/use-job-stream";
import { cn } from "@/lib/utils";

type StageId =
  | "parsing"
  | "generating_notes"
  | "extracting_graph"
  | "building_graph"
  | "slack_import"
  | "graphrag_indexing"
  | "dreaming"
  | "wiki_generation";

type StageVisualState = "idle" | "queued" | "running" | "done" | "error";

type ActivityCard = {
  id: string;
  ts: number;
  jobId: string;
  stage: string;
  title: string;
  detail?: string;
  samples?: string[];
  tone: "info" | "success" | "warning" | "error";
  kind?: string;
};

type MetricKey =
  | "entities"
  | "edges"
  | "notes"
  | "tokens"
  | "documents"
  | "communities"
  | "reports"
  | "relationships";

const INGESTION_STAGES: { id: StageId; label: string; short: string }[] = [
  { id: "parsing", label: "Parse", short: "Parse" },
  { id: "generating_notes", label: "Notes", short: "Notes" },
  { id: "extracting_graph", label: "Extract", short: "Extract" },
  { id: "building_graph", label: "Graph", short: "Graph" },
];

const EXT_STAGES: { id: StageId; label: string; short: string }[] = [
  { id: "slack_import", label: "Slack import", short: "Slack" },
  { id: "graphrag_indexing", label: "GraphRAG", short: "GR" },
  { id: "dreaming", label: "Dream", short: "Dream" },
  { id: "wiki_generation", label: "Wiki", short: "Wiki" },
];

const GRAPHRAG_STAGES: { id: StageId; label: string; short: string }[] = [
  { id: "graphrag_indexing", label: "Export corpus", short: "Export" },
  { id: "building_graph", label: "Build index", short: "Build" },
  { id: "extracting_graph", label: "Communities", short: "Comm." },
];

const METRIC_LABELS: Record<MetricKey, string> = {
  entities: "Entities",
  edges: "Edges",
  notes: "Notes",
  tokens: "Tokens",
  documents: "Documents",
  communities: "Communities",
  reports: "Reports",
  relationships: "Relationships",
};

const INGESTION_METRICS: MetricKey[] = ["entities", "edges", "notes", "tokens"];
const GRAPHRAG_METRICS: MetricKey[] = ["documents", "entities", "relationships", "communities", "reports"];

const STAGE_NARRATIVE: Record<string, string> = {
  parsing: "Reading document",
  generating_notes: "Synthesizing notes",
  extracting_graph: "Extracting graph",
  building_graph: "Building graph",
  slack_import: "Importing Slack",
  graphrag_indexing: "GraphRAG indexing",
  dreaming: "Dreaming",
  wiki_generation: "Generating wiki",
};

/** Theater feed: narrative moments only — progress % and metrics stay in Log view. */
const LOG_THEATER_BLOCK =
  /worker started|^\s*\d+\s*%|Progress\s+\d|queued_|^metric/i;
const LOG_EPISODE_LINE =
  /^episode\s+(\d+)\/(\d+):\s+\+(\d+)\s+entities,\s+\+(\d+)\s+edges/i;

function narrativeFromLog(message: string | undefined): string | null {
  const text = (message ?? "").trim();
  if (text.length < 6 || LOG_THEATER_BLOCK.test(text)) return null;
  const ep = LOG_EPISODE_LINE.exec(text);
  if (ep) {
    return `Episode ${ep[1]}/${ep[2]} — mapped ${ep[3]} entities and ${ep[4]} edges`;
  }
  const lower = text.toLowerCase();
  const markers = [
    "parsed",
    "parsing",
    "synthesi",
    "extract",
    "created",
    "graph",
    "episode",
    "transcript",
    "chunk",
    "note",
    "entity",
    "relationship",
    "export",
    "index",
    "corpus",
    "community",
    "reading",
    "draft",
    "opening",
    "examining",
    "spotted",
    "wired",
    "outlined",
    "saved",
    "llm",
    "north",
  ];
  return markers.some((m) => lower.includes(m)) ? text : null;
}

function shouldShowInTheaterFeed(ev: JobStreamEvent): boolean {
  if (ev.type === "replay_end" || ev.type === "job_resumed") return false;
  if (ev.type === "activity") {
    if (ev.kind === "heartbeat") return false;
    return true;
  }
  if (ev.type === "log" && narrativeFromLog(ev.message)) return true;
  if (ev.type === "job_completed") return true;
  if (ev.type === "job_failed") return true;
  return false;
}

function samplesFromEvent(ev: JobStreamEvent): string[] | undefined {
  const raw = ev.data?.entity_samples ?? ev.data?.note_titles;
  if (!Array.isArray(raw)) return undefined;
  return raw.filter((s): s is string => typeof s === "string" && s.length > 0).slice(0, 5);
}

function cardTone(ev: JobStreamEvent): ActivityCard["tone"] {
  if (ev.type === "job_failed" || ev.level === "error") return "error";
  if (ev.type === "job_completed" || ev.type === "stage_completed") return "success";
  if (ev.level === "warning" || ev.type === "warning") return "warning";
  return "info";
}

function cardTitle(ev: JobStreamEvent): string {
  if (ev.type === "activity" && ev.label) return ev.label;
  if (ev.type === "log" && ev.message) {
    return narrativeFromLog(ev.message) ?? ev.message;
  }
  if (ev.type === "job_completed") return "Finished — ingestion complete";
  if (ev.type === "job_failed") return `Failed — ${ev.reason ?? "unknown error"}`;
  return ev.type ?? "event";
}

function metricKeyFromName(name: string): MetricKey | null {
  const map: Record<string, MetricKey> = {
    entity_count: "entities",
    entities: "entities",
    edge_count: "edges",
    relationships: "relationships",
    note_count: "notes",
    tokens_consumed: "tokens",
    document_count: "documents",
    documents: "documents",
    communities: "communities",
    community_reports: "reports",
    text_units: "documents",
  };
  return map[name] ?? null;
}

function MetricTile({
  label,
  value,
  flash,
}: {
  label: string;
  value: number;
  flash: boolean;
}) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-lg border px-3 py-2 transition-colors duration-300",
        flash ? "border-caution/60 bg-caution/10" : "border-border bg-secondary/50",
      )}
    >
      {flash ? (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 animate-pulse bg-caution/15 motion-reduce:animate-none"
        />
      ) : null}
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="tabular-nums text-h5 text-foreground">{value.toLocaleString()}</p>
    </div>
  );
}

function StageNode({
  label,
  short,
  state,
  reducedMotion,
}: {
  label: string;
  short: string;
  state: StageVisualState;
  reducedMotion: boolean;
}) {
  const ledClass = {
    idle: "bg-muted-foreground/30",
    queued: "bg-muted-foreground/50",
    running: "bg-caution shadow-[0_0_12px_rgba(250,204,21,0.55)]",
    done: "bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.4)]",
    error: "bg-destructive shadow-[0_0_8px_rgba(239,68,68,0.45)]",
  }[state];

  return (
    <div className="flex flex-col items-center gap-1.5" title={label}>
      <div className="relative flex h-10 w-10 items-center justify-center">
        {state === "running" && !reducedMotion ? (
          <span
            aria-hidden
            className="absolute inline-flex h-full w-full animate-ping rounded-full bg-caution/40"
          />
        ) : null}
        <span
          className={cn(
            "relative inline-flex h-4 w-4 rounded-full transition-all duration-300",
            ledClass,
          )}
          aria-hidden
        />
      </div>
      <span className="max-w-[5rem] truncate text-center text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        <span className="hidden sm:inline">{label}</span>
        <span className="sm:hidden">{short}</span>
      </span>
    </div>
  );
}

function FlowConnector({ active, reducedMotion }: { active: boolean; reducedMotion: boolean }) {
  return (
    <div className="relative mx-1 mt-3 h-0.5 min-w-[1.25rem] flex-1 self-start bg-border">
      {active && !reducedMotion ? (
        <span
          aria-hidden
          className="absolute inset-y-0 left-0 w-1/3 animate-[pipeline-flow_1.2s_ease-in-out_infinite] rounded-full bg-caution/80 motion-reduce:animate-none"
        />
      ) : active ? (
        <span aria-hidden className="absolute inset-0 rounded-full bg-caution/50" />
      ) : null}
    </div>
  );
}

function ActivityCardRow({ card }: { card: ActivityCard }) {
  const toneBorder = {
    info: "border-border",
    success: "border-green-600/40 bg-green-600/5",
    warning: "border-caution/40 bg-caution/5",
    error: "border-destructive/40 bg-destructive/5",
  }[card.tone];

  const icon =
    card.kind === "thought"
      ? "↳"
      : card.kind === "graph_batch"
        ? "◆"
        : card.kind === "graphrag_workflow"
          ? "◎"
          : card.kind === "note_batch"
            ? "▤"
            : card.stage.includes("graph")
              ? "⬡"
              : card.stage.includes("notes")
                ? "▤"
                : "•";

  return (
    <li
      className={cn(
        "animate-[pipeline-slide-in_0.35s_ease-out] rounded-md border px-2.5 py-2 motion-reduce:animate-none",
        toneBorder,
        card.kind === "thought" && "border-border/80 bg-secondary/30",
      )}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 shrink-0 text-caption text-caution" aria-hidden>
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <p
              className={cn(
                "text-p text-foreground",
                card.kind === "thought" ? "leading-snug" : "truncate",
              )}
            >
              {card.title}
            </p>
            <div className="shrink-0 text-right text-[10px] text-muted-foreground">
              <p>{new Date(card.ts).toLocaleTimeString()}</p>
              <p className="font-mono">{card.jobId.slice(0, 8)}</p>
            </div>
          </div>
          {card.detail ? (
            <p className="mt-0.5 line-clamp-2 text-caption text-muted-foreground">{card.detail}</p>
          ) : null}
          {card.samples && card.samples.length > 0 ? (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {card.samples.map((name) => (
                <span
                  key={name}
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-[10px]",
                    card.kind === "graph_batch"
                      ? "border-pink-400/40 bg-pink-500/10 text-pink-100"
                      : "border-caution/30 bg-caution/10 text-foreground",
                  )}
                >
                  {name}
                </span>
              ))}
            </div>
          ) : null}
          {card.stage ? (
            <span className="mt-1 inline-block rounded border border-border bg-secondary px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-muted-foreground">
              {card.stage.replace(/_/g, " ")}
            </span>
          ) : null}
        </div>
      </div>
    </li>
  );
}

function TheaterJobWire({
  job,
  onEvent,
  onTerminal,
}: {
  job: ActiveJob;
  onEvent: (jobId: string, ev: JobStreamEvent) => void;
  onTerminal: (jobId: string) => void;
}) {
  useJobStream(job, { onEvent, onTerminal });
  return null;
}

export function PipelineActivityTheater({ expanded = false }: { expanded?: boolean }) {
  const jobs = useActiveJobs();
  const { unregisterActiveJob } = useJobEvents();
  const [stageByJob, setStageByJob] = useState<Record<string, Record<string, StageVisualState>>>(
    {},
  );
  const [metrics, setMetrics] = useState<Record<MetricKey, number>>({
    entities: 0,
    edges: 0,
    notes: 0,
    tokens: 0,
    documents: 0,
    communities: 0,
    reports: 0,
    relationships: 0,
  });
  const [flashMetric, setFlashMetric] = useState<MetricKey | null>(null);
  const [progressPct, setProgressPct] = useState(0);
  const [activeStage, setActiveStage] = useState<string | null>(null);
  const [cards, setCards] = useState<ActivityCard[]>([]);
  const [reducedMotion, setReducedMotion] = useState(false);
  const cardCounter = useRef(0);
  const feedRef = useRef<HTMLUListElement | null>(null);
  const seenFeedKeys = useRef<Set<string>>(new Set());

  const graphragMode = useMemo(
    () => jobs.some((j) => j.kind === "graphrag_index" || j.jobId.startsWith("graphrag:")),
    [jobs],
  );

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const fn = () => setReducedMotion(mq.matches);
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);

  // Seed GraphRAG stage as running for active graphrag jobs before first SSE event.
  useEffect(() => {
    for (const j of jobs) {
      if (j.kind === "graphrag_index" || j.jobId.startsWith("graphrag:")) {
        setStageByJob((prev) => ({
          ...prev,
          [j.jobId]: {
            ...(prev[j.jobId] ?? {}),
            graphrag_indexing: prev[j.jobId]?.graphrag_indexing ?? "running",
          },
        }));
      }
    }
  }, [jobs]);

  const bumpMetric = useCallback((name: string, value: number) => {
    const key = metricKeyFromName(name);
    if (!key) return;
    setMetrics((m) => ({ ...m, [key]: Math.max(m[key], value) }));
    setFlashMetric(key);
    window.setTimeout(() => setFlashMetric(null), 600);
  }, []);

  const setStage = useCallback((jobId: string, stage: string, state: StageVisualState) => {
    if (!stage) return;
    setStageByJob((prev) => ({
      ...prev,
      [jobId]: { ...(prev[jobId] ?? {}), [stage]: state },
    }));
  }, []);

  const handleEvent = useCallback(
    (jobId: string, ev: JobStreamEvent) => {
      const stage = ev.stage ?? "";

      if (ev.type === "stage_started") {
        setStage(jobId, stage, "running");
        if (stage) setActiveStage(stage);
      } else if (ev.type === "stage_completed") {
        setStage(jobId, stage, "done");
      } else if (ev.type === "stage_progress") {
        setStage(jobId, stage, "running");
        if (stage) setActiveStage(stage);
        if (typeof ev.percent === "number") {
          setProgressPct((p) => Math.max(p, ev.percent as number));
        }
        if (typeof ev.current === "number" && typeof ev.total === "number" && ev.total > 0) {
          bumpMetric("document_count", ev.current);
        }
      } else if (ev.type === "job_failed") {
        if (stage) setStage(jobId, stage, "error");
      } else if (ev.type === "job_resumed") {
        if (stage) setStage(jobId, stage, "running");
        setActiveStage(stage || "graphrag_indexing");
      } else if (ev.type === "job_completed") {
        setProgressPct(100);
        for (const s of [...INGESTION_STAGES, ...EXT_STAGES]) {
          setStage(jobId, s.id, "done");
        }
      }

      if (ev.type === "metric" && ev.name && typeof ev.value === "number") {
        bumpMetric(ev.name, ev.value);
        if (["entity_count", "edge_count", "entities", "relationships"].includes(ev.name)) {
          emitPipelineActivity({
            jobId,
            stage,
            graphTouch: true,
          });
        }
      }

      if (ev.type === "activity" && ev.data) {
        const delta = parseGraphDeltaFromActivityData(ev.data);
        if (delta) {
          emitGraphLiveDelta({ ...delta, jobId });
          emitPipelineActivity({ jobId, stage, graphTouch: true });
        }
      }

      if (!shouldShowInTheaterFeed(ev)) return;

      const title = cardTitle(ev);
      const dedupeKey = `${jobId}:${ev.type ?? "event"}:${ev.kind ?? ""}:${title}:${ev.detail ?? ""}`;
      if (seenFeedKeys.current.has(dedupeKey)) return;
      seenFeedKeys.current.add(dedupeKey);

      cardCounter.current += 1;
      const samples = samplesFromEvent(ev);
      const card: ActivityCard = {
        id: `${jobId}-${cardCounter.current}`,
        ts: Date.now(),
        jobId,
        stage,
        title,
        detail: ev.detail ?? undefined,
        samples,
        tone: cardTone(ev),
        kind: ev.kind ?? (ev.type === "log" ? "thought" : undefined),
      };
      setCards((prev) => [...prev, card].slice(-80));
    },
    [bumpMetric, setStage],
  );

  const handleTerminal = useCallback(
    (jobId: string) => {
      for (const key of Array.from(seenFeedKeys.current)) {
        if (key.startsWith(`${jobId}:`)) seenFeedKeys.current.delete(key);
      }
      window.setTimeout(() => unregisterActiveJob(jobId), 1500);
    },
    [unregisterActiveJob],
  );

  const mergedStages = useMemo(() => {
    const out: Record<string, StageVisualState> = {};
    for (const perJob of Object.values(stageByJob)) {
      for (const [sid, st] of Object.entries(perJob)) {
        const prev = out[sid];
        if (!prev || st === "running" || st === "error") out[sid] = st;
        else if (st === "done" && prev !== "running" && prev !== "error") out[sid] = st;
      }
    }
    return out;
  }, [stageByJob]);

  const visibleStages = useMemo(() => {
    if (graphragMode) {
      return GRAPHRAG_STAGES.map((s) =>
        s.id === "graphrag_indexing"
          ? s
          : s.id === "building_graph"
            ? { ...s, label: "GraphRAG build", short: "Build" }
            : s,
      );
    }
    const extActive = EXT_STAGES.some((s) => mergedStages[s.id] && mergedStages[s.id] !== "idle");
    return extActive
      ? [...INGESTION_STAGES, ...EXT_STAGES.filter((s) => mergedStages[s.id])]
      : INGESTION_STAGES;
  }, [graphragMode, mergedStages]);

  const metricKeys = graphragMode ? GRAPHRAG_METRICS : INGESTION_METRICS;

  useEffect(() => {
    if (!feedRef.current) return;
    feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [cards.length]);

  if (jobs.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-border bg-background/40 px-4 py-6 text-center">
        <p className="text-p text-muted-foreground">
          Pipeline theater idle — upload, import, or build an index to watch ingestion unfold.
        </p>
      </div>
    );
  }

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col", expanded ? "gap-4" : "gap-3")}>
      <div className={cn("flex shrink-0 flex-wrap items-center gap-2 text-caption", expanded && "text-p")}>
        <span className="relative flex h-2 w-2" aria-hidden>
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-caution opacity-60 motion-reduce:animate-none" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-caution" />
        </span>
        <span className="text-foreground">
          Live · {jobs.length} job{jobs.length === 1 ? "" : "s"}
        </span>
        {jobs.map((j) => (
          <span
            key={j.jobId}
            className="rounded-full border border-border bg-secondary px-2 py-0.5 font-mono text-[10px] text-muted-foreground"
          >
            {j.kind?.replace(/_/g, " ") ?? "job"} · {j.jobId.slice(0, 8)}
          </span>
        ))}
      </div>

      {jobs.map((j) => (
        <TheaterJobWire key={j.jobId} job={j} onEvent={handleEvent} onTerminal={handleTerminal} />
      ))}

      <div className="shrink-0 space-y-1">
        <div className="flex items-center justify-between text-caption text-muted-foreground">
          <span>{graphragMode ? "GraphRAG pipeline" : "Ingestion pipeline"}</span>
          <span className="text-foreground">
            {activeStage ? STAGE_NARRATIVE[activeStage] ?? activeStage.replace(/_/g, " ") : "Starting…"}
          </span>
        </div>
        <div
          className="h-1.5 overflow-hidden rounded-full bg-secondary"
          role="progressbar"
          aria-valuenow={progressPct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Pipeline progress ${progressPct}%`}
        >
          <div
            className="h-full rounded-full bg-caution transition-[width] duration-500 ease-out"
            style={{ width: `${Math.min(100, Math.max(progressPct, 8))}%` }}
          />
        </div>
      </div>

      <div
        className={cn(
          "relative flex shrink-0 items-center gap-1 overflow-x-auto rounded-lg border border-border px-3",
          "bg-[linear-gradient(rgba(250,204,21,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(250,204,21,0.03)_1px,transparent_1px)] bg-[size:16px_16px] bg-background/80",
          expanded ? "py-6" : "py-4",
        )}
      >
        {visibleStages.map((s, i) => {
          const state = mergedStages[s.id] ?? (graphragMode && s.id === "graphrag_indexing" ? "running" : "idle");
          const next = visibleStages[i + 1];
          const nextState = next ? mergedStages[next.id] : undefined;
          const flowActive =
            state === "running" ||
            state === "done" ||
            (nextState === "running" || nextState === "done");
          return (
            <div key={s.id} className="flex min-w-0 flex-1 items-start">
              <StageNode
                label={s.label}
                short={s.short}
                state={state}
                reducedMotion={reducedMotion}
              />
              {i < visibleStages.length - 1 ? (
                <FlowConnector active={Boolean(flowActive)} reducedMotion={reducedMotion} />
              ) : null}
            </div>
          );
        })}
      </div>

      <div className={cn("grid shrink-0 gap-2", metricKeys.length > 4 ? "grid-cols-2 sm:grid-cols-5" : "grid-cols-2 sm:grid-cols-4")}>
        {metricKeys.map((k) => (
          <MetricTile
            key={k}
            label={METRIC_LABELS[k]}
            value={metrics[k]}
            flash={flashMetric === k}
          />
        ))}
      </div>

      <ul
        ref={feedRef}
        className={cn(
          "min-h-0 flex-1 space-y-2 overflow-y-auto rounded-md border border-border bg-background/80 p-2",
          expanded && "p-3",
        )}
        aria-live="polite"
        aria-label="Pipeline activity feed"
      >
        {cards.length === 0 ? (
          <li className="px-2 py-4 text-center text-caption text-muted-foreground">
            Waiting for the pipeline to think out loud…
          </li>
        ) : (
          cards.map((c) => <ActivityCardRow key={c.id} card={c} />)
        )}
      </ul>
    </div>
  );
}
