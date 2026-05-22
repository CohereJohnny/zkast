"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useToast } from "@/components/feedback-provider";
import { type ActiveJobKind, useActiveJobs, useJobEvents } from "@/lib/job-events";
import { readApiErrorMessage } from "@/lib/api-error-message";
import { cn } from "@/lib/utils";

type PipelineJob = {
  job_id: string;
  status?: string;
  kind?: string;
  document_id?: string | null;
  agent_id?: string | null;
  progress?: { percent?: number; stage?: string } | string;
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

function progressLabel(job: PipelineJob): string {
  const p = job.progress;
  if (typeof p === "string") {
    try {
      const parsed = JSON.parse(p) as { percent?: number; stage?: string };
      if (parsed.stage) return `${parsed.stage}${parsed.percent != null ? ` ${parsed.percent}%` : ""}`;
    } catch {
      return p;
    }
  }
  if (p && typeof p === "object") {
    const stage = p.stage || job.kind || "job";
    return `${stage}${p.percent != null ? ` · ${p.percent}%` : ""}`;
  }
  return job.kind || "pipeline";
}

function pipelineKind(kind: string | undefined): ActiveJobKind | null {
  if (
    kind === "document_parse" ||
    kind === "generate_atomic_notes" ||
    kind === "extract_graph" ||
    kind === "dreaming"
  ) {
    return kind;
  }
  return null;
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

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-4">
      <div>
        <h1 className="text-h4 text-foreground">Jobs</h1>
        <p className="mt-1 text-p text-muted-foreground">
          Worker queue, live pipeline jobs (Redis), and dreaming runs. The build log below streams
          events for jobs you start from Documents, Conversations, or Agents.
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
          <p className="text-caption text-muted-foreground">Arq in progress</p>
          <p className="text-h5 text-foreground">{arq?.in_progress?.length ?? 0}</p>
        </div>
        <div className="rounded-lg border border-border bg-secondary px-3 py-3">
          <p className="text-caption text-muted-foreground">Watching (this browser)</p>
          <p className="text-h5 text-foreground">{active.length}</p>
        </div>
      </section>

      {arq?.in_progress && arq.in_progress.length > 0 ? (
        <section className="rounded-lg border border-border bg-card px-3 py-3">
          <h2 className="text-h5 text-muted-foreground">Worker in progress</h2>
          <ul className="mt-2 space-y-1 font-mono text-caption text-muted-foreground">
            {arq.in_progress.map((id) => (
              <li key={id}>{id}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="rounded-lg border border-border bg-card">
        <h2 className="border-b border-border px-3 py-2 text-h5 text-muted-foreground">
          Pipeline jobs (Redis)
        </h2>
        {pipelineJobs.length === 0 ? (
          <p className="px-3 py-4 text-caption text-muted-foreground">No recent pipeline job hashes for this workspace.</p>
        ) : (
          <ul className="divide-y divide-border-subtle">
            {pipelineJobs.map((j) => (
              <li key={j.job_id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-caption">
                <span className={cn("font-medium", statusClass(j.status))}>{j.status || "unknown"}</span>
                <span className="font-mono text-foreground">{j.job_id.slice(0, 8)}…</span>
                <span className="text-muted-foreground">{progressLabel(j)}</span>
                {j.document_id ? (
                  <Link
                    href={`/documents/${j.document_id}`}
                    className="text-muted-foreground underline hover:text-foreground"
                  >
                    document
                  </Link>
                ) : null}
                <button
                  type="button"
                  className="ml-auto rounded border border-border px-2 py-0.5 hover:bg-secondary"
                  onClick={() => {
                    registerActiveJob(
                      j.job_id,
                      workspaceId,
                      j.document_id ?? null,
                      pipelineKind(j.kind),
                    );
                    toast({
                      variant: "success",
                      message: "Subscribed to job log",
                      description: j.job_id.slice(0, 8),
                    });
                  }}
                >
                  Watch log
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-lg border border-border bg-card">
        <h2 className="border-b border-border px-3 py-2 text-h5 text-muted-foreground">
          Dream jobs (database)
        </h2>
        {dreamJobs.length === 0 ? (
          <p className="px-3 py-4 text-caption text-muted-foreground">No dream jobs yet — use Dream on an agent.</p>
        ) : (
          <ul className="divide-y divide-border-subtle">
            {dreamJobs.map((j) => (
              <li key={j.id} className="px-3 py-2 text-caption">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={cn("font-medium", statusClass(j.status))}>{j.status}</span>
                  <span className="font-mono text-foreground">{j.id.slice(0, 8)}…</span>
                  <span className="text-muted-foreground">agent {j.agent_id.slice(0, 8)}…</span>
                  {j.stats ? (
                    <span className="text-muted-foreground">
                      links {String(j.stats.links_added ?? 0)} · embeddings{" "}
                      {String(j.stats.embeddings_refreshed ?? 0)}
                    </span>
                  ) : null}
                  <Link
                    href={`/agents/${j.agent_id}`}
                    className="text-muted-foreground underline hover:text-foreground"
                  >
                    agent
                  </Link>
                  <button
                    type="button"
                    className="ml-auto rounded border border-border px-2 py-0.5 hover:bg-secondary"
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
