"use client";

import {
  BarChart3,
  ChevronRight,
  Play,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AgentPicker } from "@/components/filters/agent-picker";
import { useToast } from "@/components/feedback-provider";
import { readApiErrorMessage } from "@/lib/api-error-message";
import { cn } from "@/lib/utils";

type EvalDataset = {
  name: string;
  file: string;
  description: string;
  question_count: number;
  default_modes: string[];
};

type EvalRunListItem = {
  id: string;
  dataset_name: string;
  dataset_version?: string;
  retrieval_modes: string[];
  status: string;
  notes?: string | null;
  eval_kind?: string;
  agent_id?: string | null;
  top_k_cutoffs?: number[];
  summary?: Record<string, unknown> | null;
  created_at?: string;
  completed_at?: string | null;
};

type EvalQuestion = {
  id: string;
  question_key: string;
  category: string;
  ability_type?: string | null;
  question_text: string;
  expected_answer_patterns?: string[];
  expected_entity_ids?: string[];
  expected_source_ids?: string[];
  expected_context_patterns?: string[];
  refusal_expected?: boolean;
  notes?: string;
};

type EvalResult = {
  id: string;
  question_id: string;
  retrieval_mode: string;
  memory_system?: string | null;
  top_k_cutoff?: number;
  answer_text: string;
  refused: boolean;
  scores: Record<string, unknown>;
  retrieval_items?: Array<{
    source_id?: string;
    source_kind?: string;
    score?: number;
    excerpt?: string;
  }> | null;
  latency_ms?: number | null;
  tokens_in?: number | null;
  tokens_out?: number | null;
};

type EvalRunDetail = {
  run: EvalRunListItem;
  questions: EvalQuestion[];
  results: EvalResult[];
};

const MEMORY_MODES: { id: string; label: string }[] = [
  { id: "rag", label: "Raw / RAG" },
  { id: "raw_transcript", label: "Raw transcript" },
  { id: "zettelkasten_notes", label: "Zettel notes" },
  { id: "amem_lite", label: "A-MEM lite" },
  { id: "graph", label: "Graph" },
  { id: "hybrid", label: "Hybrid" },
];

const RUN_MODES = [
  { id: "full", label: "Full (retrieve + answer + score)" },
  { id: "retrieve_only", label: "Retrieve only" },
] as const;

const TOP_K_PRESETS = [
  { label: "10, 30", value: [10, 30] },
  { label: "10, 20, 50", value: [10, 20, 50] },
  { label: "30 only", value: [30] },
];

function pct(rate: number | undefined) {
  if (rate == null || Number.isNaN(rate)) return "—";
  return `${Math.round(rate * 100)}%`;
}

function statusChip(status: string) {
  const s = status.toLowerCase();
  const cls =
    s === "complete"
      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
      : s === "running"
        ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
        : s === "failed"
          ? "bg-red-500/15 text-red-700 dark:text-red-300"
          : "bg-surface-raised text-muted";
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-caption font-medium", cls)}>
      {status}
    </span>
  );
}

export function EvalsPanel({
  workspaceId,
  initialRunId,
}: {
  workspaceId: string;
  initialRunId?: string | null;
}) {
  const toast = useToast();
  const [datasets, setDatasets] = useState<EvalDataset[]>([]);
  const [runs, setRuns] = useState<EvalRunListItem[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(initialRunId ?? null);
  const [detail, setDetail] = useState<EvalRunDetail | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [starting, setStarting] = useState(false);
  const [filter, setFilter] = useState("");

  const [datasetName, setDatasetName] = useState("oil_gas_v1");
  const [selectedModes, setSelectedModes] = useState<string[]>(["rag", "graph", "hybrid"]);
  const [agentId, setAgentId] = useState("");
  const [topKPreset, setTopKPreset] = useState(0);
  const [runMode, setRunMode] = useState<(typeof RUN_MODES)[number]["id"]>("full");
  const [notes, setNotes] = useState("");

  const [inspectorQid, setInspectorQid] = useState<string | null>(null);
  const [inspectorMode, setInspectorMode] = useState<string | null>(null);
  const [inspectorK, setInspectorK] = useState<number | null>(null);

  const loadDatasets = useCallback(async () => {
    const res = await fetch("/api/v1/eval/datasets");
    if (!res.ok) return;
    const data = (await res.json()) as { items?: EvalDataset[] };
    setDatasets(data.items ?? []);
  }, []);

  const loadRuns = useCallback(async () => {
    setLoadingRuns(true);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/eval/runs`,
      );
      if (!res.ok) {
        toast({
          variant: "error",
          message: readApiErrorMessage(res, "Failed to load eval runs"),
        });
        return;
      }
      const data = (await res.json()) as { items?: EvalRunListItem[] };
      setRuns(data.items ?? []);
    } finally {
      setLoadingRuns(false);
    }
  }, [workspaceId, toast]);

  const loadDetail = useCallback(
    async (runId: string) => {
      setLoadingDetail(true);
      try {
        const res = await fetch(
          `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/eval/runs/${encodeURIComponent(runId)}`,
        );
        if (!res.ok) {
          toast({
            variant: "error",
            message: readApiErrorMessage(res, "Failed to load eval run"),
          });
          return;
        }
        const data = (await res.json()) as EvalRunDetail;
        setDetail(data);
      } finally {
        setLoadingDetail(false);
      }
    },
    [workspaceId, toast],
  );

  useEffect(() => {
    void loadDatasets();
    void loadRuns();
  }, [loadDatasets, loadRuns]);

  useEffect(() => {
    const ds = datasets.find((d) => d.name === datasetName);
    if (ds?.default_modes?.length) {
      setSelectedModes(ds.default_modes);
    }
  }, [datasetName, datasets]);

  useEffect(() => {
    if (!selectedRunId) {
      setDetail(null);
      return;
    }
    void loadDetail(selectedRunId);
  }, [selectedRunId, loadDetail]);

  useEffect(() => {
    if (!selectedRunId) return;
    const run = runs.find((r) => r.id === selectedRunId);
    if (run?.status === "running") {
      const t = setInterval(() => {
        void loadRuns();
        void loadDetail(selectedRunId);
      }, 4000);
      return () => clearInterval(t);
    }
  }, [selectedRunId, runs, loadRuns, loadDetail]);

  const filteredRuns = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return runs;
    return runs.filter(
      (r) =>
        r.dataset_name.toLowerCase().includes(q) ||
        r.status.toLowerCase().includes(q) ||
        (r.notes ?? "").toLowerCase().includes(q),
    );
  }, [runs, filter]);

  const summary = (detail?.run.summary ?? {}) as {
    modes?: Record<
      string,
      {
        pattern_match_rate?: number;
        citation_recall_avg?: number;
        context_recall_avg?: number;
        refusal_correct_rate?: number;
        n?: number;
      }
    >;
    categories?: Record<string, Record<string, { pattern_match_rate?: number; n?: number }>>;
    abilities?: Record<string, Record<string, { pattern_match_rate?: number; n?: number }>>;
    top_k?: Record<string, { pattern_match_rate?: number; context_recall_avg?: number }>;
  };

  const inspectorResult = useMemo(() => {
    if (!detail || !inspectorQid) return null;
    return (
      detail.results.find(
        (r) =>
          r.question_id === inspectorQid &&
          (inspectorMode == null || r.retrieval_mode === inspectorMode) &&
          (inspectorK == null || r.top_k_cutoff === inspectorK),
      ) ?? null
    );
  }, [detail, inspectorQid, inspectorMode, inspectorK]);

  const inspectorQuestion = useMemo(() => {
    if (!detail || !inspectorQid) return null;
    return detail.questions.find((q) => q.id === inspectorQid) ?? null;
  }, [detail, inspectorQid]);

  const toggleMode = (mode: string) => {
    setSelectedModes((prev) =>
      prev.includes(mode) ? prev.filter((m) => m !== mode) : [...prev, mode],
    );
  };

  const startRun = async () => {
    if (selectedModes.length === 0) {
      toast({
        variant: "error",
        message: "Select at least one memory system / retrieval mode.",
      });
      return;
    }
    setStarting(true);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/eval/runs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            dataset_name: datasetName,
            retrieval_modes: selectedModes,
            agent_id: agentId || undefined,
            top_k_cutoffs: TOP_K_PRESETS[topKPreset]?.value ?? [10, 30],
            run_mode: runMode,
            notes: notes || undefined,
            eval_kind: "memory_system",
          }),
        },
      );
      if (!res.ok) {
        toast({
          variant: "error",
          message: readApiErrorMessage(res, "Failed to start eval run"),
        });
        return;
      }
      const data = (await res.json()) as { run_id?: string };
      toast({ variant: "success", message: "Eval run started" });
      await loadRuns();
      if (data.run_id) {
        setSelectedRunId(data.run_id);
      }
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <header>
        <h1 className="flex items-center gap-2 text-title-2 text-primary">
          <BarChart3 className="h-5 w-5" strokeWidth={1.5} aria-hidden />
          Memory evals
        </h1>
        <p className="mt-1 max-w-2xl text-body text-secondary">
          Compare memory systems and retrieval modes on canned datasets. Inspect per-question
          retrieval contexts, answers, and scores.
        </p>
      </header>

      <section className="rounded-lg border border-border-subtle bg-surface p-4">
        <h2 className="text-title-3 text-primary">Start run</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="flex flex-col gap-1 text-caption text-muted">
            Dataset
            <select
              value={datasetName}
              onChange={(e) => setDatasetName(e.target.value)}
              className="rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 text-body text-primary"
            >
              {datasets.map((d) => (
                <option key={d.name} value={d.name}>
                  {d.name} ({d.question_count} questions)
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-caption text-muted">
            Run mode
            <select
              value={runMode}
              onChange={(e) =>
                setRunMode(e.target.value as (typeof RUN_MODES)[number]["id"])
              }
              className="rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 text-body text-primary"
            >
              {RUN_MODES.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-caption text-muted">
            Top-K cutoffs
            <select
              value={topKPreset}
              onChange={(e) => setTopKPreset(Number(e.target.value))}
              className="rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 text-body text-primary"
            >
              {TOP_K_PRESETS.map((p, i) => (
                <option key={p.label} value={i}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <div className="sm:col-span-2 lg:col-span-3">
            <AgentPicker
              workspaceId={workspaceId}
              value={agentId}
              onChange={setAgentId}
              label="Agent scope (optional)"
              placeholder="Workspace-wide — all agents"
            />
          </div>
        </div>
        <div className="mt-3">
          <p className="text-caption text-muted">Memory systems / retrieval modes</p>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {MEMORY_MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                onClick={() => toggleMode(m.id)}
                className={cn(
                  "cursor-pointer rounded-md border px-2 py-1 text-caption transition",
                  selectedModes.includes(m.id)
                    ? "border-accent-primary bg-accent-primary/10 text-primary"
                    : "border-border-subtle text-secondary hover:bg-surface-raised",
                )}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
        <label className="mt-3 flex flex-col gap-1 text-caption text-muted">
          Notes (optional)
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="e.g. post-dream baseline"
            className="rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 text-body text-primary"
          />
        </label>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            disabled={starting}
            onClick={() => void startRun()}
            className="inline-flex cursor-pointer items-center gap-2 rounded-md bg-accent-primary px-3 py-2 text-body font-medium text-on-accent transition hover:opacity-90 disabled:opacity-50"
          >
            <Play className="h-4 w-4" aria-hidden />
            {starting ? "Starting…" : "Start eval run"}
          </button>
          <button
            type="button"
            onClick={() => void loadRuns()}
            className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-border-subtle px-3 py-2 text-body text-secondary transition hover:bg-surface-raised"
          >
            <RefreshCw className="h-4 w-4" aria-hidden />
            Refresh
          </button>
        </div>
      </section>

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(220px,280px)_1fr]">
        <aside className="flex min-h-0 flex-col rounded-lg border border-border-subtle bg-surface">
          <div className="border-b border-border-subtle p-3">
            <p className="text-title-3 text-primary">Runs</p>
            <div className="relative mt-2">
              <Search
                className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted"
                aria-hidden
              />
              <input
                type="search"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter runs…"
                className="w-full rounded-md border border-border-subtle bg-surface-raised py-1.5 pl-7 pr-7 text-body text-primary"
              />
              {filter ? (
                <button
                  type="button"
                  onClick={() => setFilter("")}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 cursor-pointer rounded p-0.5 text-muted hover:text-primary"
                  aria-label="Clear filter"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              ) : null}
            </div>
          </div>
          <ul className="min-h-0 flex-1 overflow-y-auto p-2">
            {loadingRuns ? (
              <li className="px-2 py-3 text-caption text-muted">Loading…</li>
            ) : filteredRuns.length === 0 ? (
              <li className="px-2 py-3 text-caption text-muted">No eval runs yet.</li>
            ) : (
              filteredRuns.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedRunId(r.id)}
                    className={cn(
                      "flex w-full cursor-pointer flex-col gap-0.5 rounded-md px-2 py-2 text-left transition hover:bg-surface-raised",
                      selectedRunId === r.id && "bg-surface-raised",
                    )}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-body font-medium text-primary">
                        {r.dataset_name}
                      </span>
                      {statusChip(r.status)}
                    </span>
                    <span className="truncate text-caption text-muted">
                      {(r.retrieval_modes ?? []).join(", ")} · k=
                      {(r.top_k_cutoffs ?? [30]).join(",")}
                    </span>
                    <span className="text-caption text-muted">
                      {r.created_at ? new Date(r.created_at).toLocaleString() : ""}
                    </span>
                  </button>
                </li>
              ))
            )}
          </ul>
        </aside>

        <main className="flex min-h-0 flex-col gap-4 overflow-y-auto">
          {!selectedRunId ? (
            <p className="text-body text-muted">Select a run to view summary and per-question results.</p>
          ) : loadingDetail && !detail ? (
            <p className="text-body text-muted">Loading run detail…</p>
          ) : detail ? (
            <>
              <section className="rounded-lg border border-border-subtle bg-surface p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-title-3 text-primary">{detail.run.dataset_name}</h2>
                  {statusChip(detail.run.status)}
                  <span className="text-caption text-muted">
                    Run {detail.run.id.slice(0, 8)}…
                  </span>
                </div>
                {summary.modes && Object.keys(summary.modes).length > 0 ? (
                  <div className="mt-4 overflow-x-auto">
                    <table className="w-full min-w-[480px] text-left text-caption">
                      <thead>
                        <tr className="border-b border-border-subtle text-muted">
                          <th className="py-1 pr-3">Mode</th>
                          <th className="py-1 pr-3">Pattern match</th>
                          <th className="py-1 pr-3">Citation recall</th>
                          <th className="py-1 pr-3">Context recall</th>
                          <th className="py-1 pr-3">Refusal</th>
                          <th className="py-1">n</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(summary.modes).map(([mode, stats]) => (
                          <tr key={mode} className="border-b border-border-subtle/60">
                            <td className="py-1.5 pr-3 font-medium text-primary">{mode}</td>
                            <td className="py-1.5 pr-3">{pct(stats.pattern_match_rate)}</td>
                            <td className="py-1.5 pr-3">{pct(stats.citation_recall_avg)}</td>
                            <td className="py-1.5 pr-3">{pct(stats.context_recall_avg)}</td>
                            <td className="py-1.5 pr-3">{pct(stats.refusal_correct_rate)}</td>
                            <td className="py-1.5">{stats.n ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : detail.run.status === "running" ? (
                  <p className="mt-3 text-body text-muted">Run in progress — scores appear when complete.</p>
                ) : null}

                {summary.abilities && Object.keys(summary.abilities).length > 0 ? (
                  <div className="mt-4">
                    <h3 className="text-body font-medium text-primary">By ability type</h3>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {Object.entries(summary.abilities).map(([ability, byMode]) => (
                        <div
                          key={ability}
                          className="rounded-md border border-border-subtle px-2 py-1.5 text-caption"
                        >
                          <span className="font-medium text-primary">{ability}</span>
                          {Object.entries(byMode).map(([mode, st]) => (
                            <span key={mode} className="ml-2 text-muted">
                              {mode}: {pct(st.pattern_match_rate)}
                            </span>
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </section>

              <section className="rounded-lg border border-border-subtle bg-surface p-4">
                <h3 className="text-title-3 text-primary">Questions</h3>
                <ul className="mt-2 divide-y divide-border-subtle">
                  {detail.questions.map((q) => {
                    const qResults = detail.results.filter((r) => r.question_id === q.id);
                    const best = qResults.find(
                      (r) => (r.scores as { pattern_match?: boolean }).pattern_match,
                    );
                    return (
                      <li key={q.id} className="py-2">
                        <button
                          type="button"
                          onClick={() => {
                            setInspectorQid(q.id);
                            const first = qResults[0];
                            setInspectorMode(first?.retrieval_mode ?? null);
                            setInspectorK(first?.top_k_cutoff ?? null);
                          }}
                          className="flex w-full cursor-pointer items-start gap-2 text-left transition hover:text-primary"
                        >
                          <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />
                          <div className="min-w-0 flex-1">
                            <p className="text-body text-primary">{q.question_text}</p>
                            <p className="mt-0.5 text-caption text-muted">
                              {q.ability_type ?? q.category} · {q.question_key} ·{" "}
                              {qResults.length} results
                              {best ? " · has match" : ""}
                            </p>
                          </div>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </section>

              {inspectorQuestion && inspectorResult ? (
                <section className="rounded-lg border border-border-subtle bg-surface p-4">
                  <h3 className="text-title-3 text-primary">Question inspector</h3>
                  <p className="mt-2 text-body text-secondary">{inspectorQuestion.question_text}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {detail.results
                      .filter((r) => r.question_id === inspectorQid)
                      .map((r) => (
                        <button
                          key={r.id}
                          type="button"
                          onClick={() => {
                            setInspectorMode(r.retrieval_mode);
                            setInspectorK(r.top_k_cutoff ?? null);
                          }}
                          className={cn(
                            "cursor-pointer rounded border px-2 py-1 text-caption transition",
                            inspectorResult.id === r.id
                              ? "border-accent-primary bg-accent-primary/10 text-primary"
                              : "border-border-subtle text-muted hover:bg-surface-raised",
                          )}
                        >
                          {r.memory_system ?? r.retrieval_mode} k={r.top_k_cutoff}
                        </button>
                      ))}
                  </div>
                  <div className="mt-4 grid gap-4 lg:grid-cols-2">
                    <div>
                      <h4 className="text-body font-medium text-primary">Answer</h4>
                      <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-surface-raised p-2 text-caption text-secondary">
                        {inspectorResult.answer_text}
                      </pre>
                      <p className="mt-2 text-caption text-muted">
                        Pattern:{" "}
                        {(inspectorResult.scores as { pattern_match?: boolean }).pattern_match
                          ? "match"
                          : "miss"}{" "}
                        · Citation recall:{" "}
                        {String(
                          (inspectorResult.scores as { citation_recall?: number })
                            .citation_recall ?? "—",
                        )}{" "}
                        · Context recall:{" "}
                        {String(
                          (inspectorResult.scores as { context_recall?: number })
                            .context_recall ?? "—",
                        )}{" "}
                        · {inspectorResult.latency_ms ?? "—"} ms
                      </p>
                    </div>
                    <div>
                      <h4 className="text-body font-medium text-primary">Retrieved contexts</h4>
                      <ul className="mt-1 max-h-64 space-y-2 overflow-y-auto">
                        {(inspectorResult.retrieval_items ?? []).length === 0 ? (
                          <li className="text-caption text-muted">No retrieval snapshot stored.</li>
                        ) : (
                          (inspectorResult.retrieval_items ?? []).map((item, i) => (
                            <li
                              key={`${item.source_id}-${i}`}
                              className="rounded-md border border-border-subtle bg-surface-raised p-2 text-caption"
                            >
                              <span className="font-medium text-primary">
                                {item.source_kind}:{item.source_id}
                              </span>
                              {item.score != null ? (
                                <span className="ml-2 text-muted">score={item.score}</span>
                              ) : null}
                              {item.excerpt ? (
                                <p className="mt-1 text-secondary">{item.excerpt}</p>
                              ) : null}
                            </li>
                          ))
                        )}
                      </ul>
                    </div>
                  </div>
                </section>
              ) : null}
            </>
          ) : null}
        </main>
      </div>
    </div>
  );
}
