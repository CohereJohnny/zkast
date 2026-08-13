"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useToast } from "@/components/feedback-provider";
import { type ActiveJobKind, useActiveJobs, useJobEvents } from "@/lib/job-events";
import { readApiErrorMessage } from "@/lib/api-error-message";
import { arqEntryJobId } from "@/lib/arq-job-id";
import { cn } from "@/lib/utils";

type PipelineJob = {
  job_id: string;
  status?: string;
  kind?: string;
  document_id?: string | null;
  agent_id?: string | null;
  progress?: { percent?: number; stage?: string; message?: string } | string;
  created_at?: string | null;
  updated_at?: string | null;
  submitted_at?: string | null;
  title?: string;
  stage_label?: string;
  stage?: string;
  percent?: number | null;
  progress_current?: number | null;
  progress_total?: number | null;
  progress_unit?: string | null;
  worker_active?: boolean;
  arq_function?: string | null;
  document_filename?: string | null;
  document_status?: string | null;
  ingestion_started_at?: string | null;
};

type DreamJob = {
  id: string;
  agent_id: string;
  status: string;
  stats?: Record<string, unknown>;
  failure_reason?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
};

type Overview = {
  arq?: { queue_depth?: number | null; in_progress?: string[] };
  pipeline_jobs?: PipelineJob[];
  dream_jobs?: DreamJob[];
};

function statusClass(status: string | undefined): string {
  const s = (status || "").toLowerCase();
  if (s === "running" || s === "queued") return "text-foreground";
  if (s === "succeeded") return "text-green-600 dark:text-green-400";
  if (s === "failed") return "text-destructive";
  return "text-muted-foreground";
}

function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const sec = Math.round((Date.now() - then) / 1000);
  if (sec < 10) return "just now";
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 48) return `${hr}h ago`;
  return new Date(iso).toLocaleString();
}

function formatAbsoluteTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString();
}

function pipelineKind(kind: string | undefined): ActiveJobKind | null {
  if (
    kind === "document_parse" ||
    kind === "generate_atomic_notes" ||
    kind === "extract_graph" ||
    kind === "dreaming" ||
    kind === "graphrag_index"
  ) {
    return kind;
  }
  return null;
}

function isJobActive(job: PipelineJob): boolean {
  const status = (job.status || "").toLowerCase();
  return Boolean(job.worker_active) || status === "running" || status === "queued";
}

function JobProgressBar({ job }: { job: PipelineJob }) {
  const active = isJobActive(job);
  if (!active && (job.percent == null || job.percent <= 0)) return null;

  const total = job.progress_total ?? 0;
  const current = job.progress_current ?? 0;
  const hasCounts = total > 0;
  const pct = Math.min(
    100,
    Math.max(
      0,
      job.percent ??
        (hasCounts ? Math.round((100 * current) / total) : active ? 50 : 0),
    ),
  );
  const indeterminate = active && !hasCounts && pct <= 0;

  return (
    <div className="mt-2 space-y-1">
      <div className="flex items-center justify-between gap-2 text-caption">
        <span className="text-muted-foreground">
          {job.stage_label || "In progress"}
          {hasCounts ? (
            <span className="tabular-nums text-foreground">
              {" "}
              · {current.toLocaleString()}/{total.toLocaleString()}{" "}
              {job.progress_unit ?? "items"}
            </span>
          ) : null}
        </span>
        <span className="tabular-nums font-medium text-foreground">
          {indeterminate ? "…" : `${pct}%`}
        </span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-secondary"
        role="progressbar"
        aria-valuenow={indeterminate ? undefined : pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${job.title || "Job"} progress`}
      >
        {indeterminate ? (
          <div className="h-full w-1/3 animate-pulse rounded-full bg-caution" />
        ) : (
          <div
            className="h-full rounded-full bg-caution transition-[width] duration-500 ease-out"
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
    </div>
  );
}

function JobStatusBadge({ job }: { job: PipelineJob }) {
  const active = isJobActive(job);
  const status = (job.status || "unknown").toLowerCase();
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium capitalize",
        active && "border-caution/50 bg-caution/15 text-foreground",
        !active && status === "succeeded" && "border-green-600/30 bg-green-600/10 text-green-700 dark:text-green-400",
        !active && status === "failed" && "border-destructive/40 bg-destructive/10 text-destructive",
        !active && status !== "succeeded" && status !== "failed" && "border-border bg-secondary text-muted-foreground",
      )}
    >
      {active ? (
        <span className="relative flex h-2 w-2" aria-hidden>
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-caution opacity-60" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-caution" />
        </span>
      ) : null}
      {active ? "running" : status}
    </span>
  );
}

function PipelineJobRow({
  job,
  onWatch,
}: {
  job: PipelineJob;
  onWatch: () => void;
}) {
  const active = isJobActive(job);
  const submitted = job.submitted_at || job.created_at || job.ingestion_started_at;
  const updated = job.updated_at;

  return (
    <li
      className={cn(
        "grid gap-2 px-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center",
        active && "bg-caution/5",
      )}
    >
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <JobStatusBadge job={job} />
          <span className="truncate text-p font-medium text-foreground">
            {job.title || job.document_filename || "Pipeline job"}
          </span>
        </div>
        <JobProgressBar job={job} />
        <p className="font-mono text-[11px] text-muted-foreground">
          {job.job_id}
          {job.document_id ? (
            <>
              {" "}
              ·{" "}
              <Link
                href={`/documents/${job.document_id}`}
                className="text-link underline-offset-2 hover:underline"
              >
                open document
              </Link>
            </>
          ) : null}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3 sm:justify-end">
        <div className="text-right text-caption">
          <p className="text-muted-foreground">Submitted</p>
          <p className="tabular-nums text-foreground" title={formatAbsoluteTime(submitted)}>
            {formatRelativeTime(submitted)}
          </p>
          {updated && updated !== submitted ? (
            <p className="mt-0.5 text-[11px] text-muted-foreground" title={formatAbsoluteTime(updated)}>
              updated {formatRelativeTime(updated)}
            </p>
          ) : null}
        </div>
        <button
          type="button"
          className={cn(
            "rounded border px-2 py-1 text-caption hover:bg-secondary",
            active ? "border-caution/50 text-foreground" : "border-border text-muted-foreground",
          )}
          onClick={onWatch}
        >
          Watch log
        </button>
      </div>
    </li>
  );
}

export function JobsPageClient({ workspaceId }: { workspaceId: string }) {
  const toast = useToast();
  const active = useActiveJobs();
  const { registerActiveJob } = useJobEvents();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/jobs/overview`,
        { cache: "no-store" },
      );
      const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        setError(readApiErrorMessage(body, `HTTP ${res.status}`));
        return;
      }
      setOverview(body as Overview);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load jobs");
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
    const t = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(t);
  }, [load]);

  const arq = overview?.arq;
  const pipelineJobs = overview?.pipeline_jobs ?? [];
  const dreamJobs = overview?.dream_jobs ?? [];

  const { activeJobs, recentJobs } = useMemo(() => {
    const act: PipelineJob[] = [];
    const recent: PipelineJob[] = [];
    for (const j of pipelineJobs) {
      if (isJobActive(j)) act.push(j);
      else recent.push(j);
    }
    return { activeJobs: act, recentJobs: recent };
  }, [pipelineJobs]);

  const arqUnlinked = useMemo(() => {
    const linked = new Set(activeJobs.map((j) => j.job_id));
    return (arq?.in_progress ?? []).filter((entry) => {
      const id = arqEntryJobId(entry);
      return id && !id.startsWith("cron:") && !linked.has(id);
    });
  }, [arq?.in_progress, activeJobs]);

  const watchJob = (j: PipelineJob) => {
    registerActiveJob(
      j.job_id,
      workspaceId,
      j.document_id ?? null,
      pipelineKind(j.kind),
    );
    toast({
      variant: "success",
      message: "Subscribed to job log",
      description: j.title || j.job_id.slice(0, 8),
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-4">
      <div>
        <h1 className="text-h4 text-foreground">Jobs</h1>
        <p className="mt-1 text-p text-muted-foreground">
          Live pipeline work for this workspace. Active jobs appear first; submitted times are
          shown relative to now.
        </p>
      </div>

      {error ? (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-p text-destructive">
          {error}
        </p>
      ) : null}

      <section className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border bg-secondary px-3 py-3">
          <p className="text-caption text-muted-foreground">Arq queue depth</p>
          <p className="text-h5 text-foreground">{arq?.queue_depth ?? "—"}</p>
        </div>
        <div className="rounded-lg border border-border bg-secondary px-3 py-3">
          <p className="text-caption text-muted-foreground">Worker tasks in flight</p>
          <p className="text-h5 text-foreground">{arq?.in_progress?.length ?? 0}</p>
        </div>
        <div className="rounded-lg border border-border bg-secondary px-3 py-3">
          <p className="text-caption text-muted-foreground">Watching (this browser)</p>
          <p className="text-h5 text-foreground">{active.length}</p>
        </div>
      </section>

      <section className="rounded-lg border border-border bg-card">
        <h2 className="border-b border-border px-3 py-2 text-h5 text-foreground">
          Active now
          {activeJobs.length > 0 ? (
            <span className="ml-2 text-caption font-normal text-muted-foreground">
              {activeJobs.length} job{activeJobs.length === 1 ? "" : "s"}
            </span>
          ) : null}
        </h2>
        {activeJobs.length === 0 && arqUnlinked.length === 0 ? (
          <p className="px-3 py-4 text-caption text-muted-foreground">
            No running pipeline jobs. When you upload or retry a document, it will appear here with
            a progress bar.
          </p>
        ) : (
          <ul className="divide-y divide-border-subtle">
            {activeJobs.map((j) => (
              <PipelineJobRow
                key={j.job_id}
                job={j}
                onWatch={() => watchJob(j)}
              />
            ))}
            {arqUnlinked.map((entry) => {
              const jobId = arqEntryJobId(entry);
              const isGraphrag = jobId.startsWith("graphrag:");
              return (
                <li
                  key={entry}
                  className="border-t border-border-subtle bg-caution/5 px-3 py-3 text-caption"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-foreground">
                      {isGraphrag ? "GraphRAG index build" : "Worker task (syncing…)"}
                    </p>
                    <button
                      type="button"
                      className="ml-auto rounded border border-caution/50 px-2 py-1 text-foreground hover:bg-secondary"
                      onClick={() => {
                        registerActiveJob(
                          jobId,
                          workspaceId,
                          null,
                          isGraphrag ? "graphrag_index" : null,
                        );
                        toast({
                          variant: "success",
                          message: "Subscribed to job log",
                          description: jobId.slice(0, 24),
                        });
                      }}
                    >
                      Watch log
                    </button>
                  </div>
                  <p className="mt-1 font-mono text-muted-foreground">{entry}</p>
                  {!isGraphrag ? (
                    <p className="mt-1 text-muted-foreground">
                      Refresh in a few seconds for progress.
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="rounded-lg border border-border bg-card">
        <h2 className="border-b border-border px-3 py-2 text-h5 text-muted-foreground">
          Recent jobs
          <span className="ml-2 text-caption font-normal">newest first</span>
        </h2>
        {recentJobs.length === 0 ? (
          <p className="px-3 py-4 text-caption text-muted-foreground">
            No completed or failed jobs in the recent window.
          </p>
        ) : (
          <ul className="divide-y divide-border-subtle">
            {recentJobs.map((j) => (
              <PipelineJobRow
                key={j.job_id}
                job={j}
                onWatch={() => watchJob(j)}
              />
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-lg border border-border bg-card">
        <h2 className="border-b border-border px-3 py-2 text-h5 text-muted-foreground">
          Dream jobs (database)
        </h2>
        {dreamJobs.length === 0 ? (
          <p className="px-3 py-4 text-caption text-muted-foreground">
            No dream jobs yet — use Dream on an agent.
          </p>
        ) : (
          <ul className="divide-y divide-border-subtle">
            {dreamJobs.map((j) => (
              <li key={j.id} className="px-3 py-3 text-caption">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={cn("font-medium capitalize", statusClass(j.status))}>
                    {j.status}
                  </span>
                  <span className="text-foreground">Dream run</span>
                  <span className="text-muted-foreground" title={formatAbsoluteTime(j.started_at)}>
                    {formatRelativeTime(j.started_at)}
                  </span>
                  <span className="font-mono text-[11px] text-muted-foreground">{j.id}</span>
                  <Link
                    href={`/agents/${j.agent_id}`}
                    className="text-link underline-offset-2 hover:underline"
                  >
                    agent
                  </Link>
                  <button
                    type="button"
                    className="ml-auto rounded border border-border px-2 py-1 hover:bg-secondary"
                    onClick={() => {
                      registerActiveJob(j.id, workspaceId, null, "dreaming");
                      toast({ variant: "success", message: "Subscribed to dream job log" });
                    }}
                  >
                    Watch log
                  </button>
                </div>
                {j.failure_reason ? (
                  <p className="mt-1 text-destructive">{j.failure_reason}</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
