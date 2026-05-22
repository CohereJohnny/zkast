"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { readApiErrorMessage } from "@/lib/api-error-message";
import { useJobEvents } from "@/lib/job-events";
import { cn } from "@/lib/utils";

type DreamJob = {
  id: string;
  status: string;
  stats?: Record<string, unknown>;
  failure_reason?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
};

type DreamJobDetail = {
  job: DreamJob;
  mutations: { id: string; mutation_type: string; note_id: string }[];
};

export function DreamJobStatus({
  workspaceId,
  agentId,
  jobId,
  onDone,
}: {
  workspaceId: string;
  agentId: string;
  jobId: string | null;
  onDone?: (status: "succeeded" | "failed") => void;
}) {
  const { requestOpenLogConsole } = useJobEvents();
  const [detail, setDetail] = useState<DreamJobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const terminalNotified = useRef(false);

  const load = useCallback(async () => {
    if (!jobId) return;
    try {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/dream-jobs/${encodeURIComponent(jobId)}`,
        { cache: "no-store" },
      );
      const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        setError(readApiErrorMessage(body, `HTTP ${res.status}`));
        return;
      }
      setDetail(body as unknown as DreamJobDetail);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dream job");
    }
  }, [workspaceId, jobId]);

  const loadRecent = useCallback(async () => {
    try {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/north/agents/${agentId}/dream-jobs?limit=1`,
        { cache: "no-store" },
      );
      const body = (await res.json().catch(() => ({}))) as { items?: DreamJob[] };
      const latest = body.items?.[0];
      if (latest?.id) {
        const dres = await fetch(
          `/api/v1/workspaces/${workspaceId}/dream-jobs/${encodeURIComponent(latest.id)}`,
        );
        if (dres.ok) {
          setDetail((await dres.json()) as DreamJobDetail);
        }
      }
    } catch {
      /* ignore */
    }
  }, [workspaceId, agentId]);

  useEffect(() => {
    if (!jobId) {
      void loadRecent();
      return;
    }
    void load();
    const status = detail?.job?.status;
    if (status === "succeeded" || status === "failed") {
      return;
    }
    const t = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(t);
  }, [jobId, load, loadRecent, detail?.job?.status]);

  useEffect(() => {
    const status = detail?.job?.status;
    if (terminalNotified.current) return;
    if (status === "succeeded") {
      terminalNotified.current = true;
      onDone?.("succeeded");
    } else if (status === "failed") {
      terminalNotified.current = true;
      onDone?.("failed");
    }
  }, [detail?.job?.status, onDone]);

  const job = detail?.job;
  if (!job && !error) return null;

  const stats = job?.stats ?? {};
  const terminal = job?.status === "succeeded" || job?.status === "failed";

  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-secondary px-3 py-2 text-caption",
        job?.status === "failed" && "border-destructive/40",
      )}
    >
      {error ? <p className="text-destructive">{error}</p> : null}
      {job ? (
        <div className="space-y-1">
          <p className="text-muted-foreground">
            Dream job{" "}
            <span className="font-mono text-foreground">{job.id.slice(0, 8)}…</span> ·{" "}
            <span
              className={cn(
                job.status === "running" && "text-foreground",
                job.status === "succeeded" && "text-green-600 dark:text-green-400",
                job.status === "failed" && "text-destructive",
              )}
            >
              {job.status}
            </span>
          </p>
          {terminal && typeof stats === "object" ? (
            <p className="text-muted-foreground">
              notes {String(stats.notes_considered ?? 0)} · pairs{" "}
              {String(stats.pairs_considered ?? 0)} · links{" "}
              {String(stats.links_added ?? 0)} · neighbors{" "}
              {String(stats.neighbors_updated ?? 0)} · embeddings{" "}
              {String(stats.embeddings_refreshed ?? 0)}
            </p>
          ) : !terminal ? (
            <p className="text-muted-foreground" role="status">
              Running…
            </p>
          ) : null}
          {job.failure_reason ? (
            <p className="text-destructive">{job.failure_reason}</p>
          ) : null}
          {detail?.mutations?.length ? (
            <p className="text-muted-foreground">{detail.mutations.length} mutation(s) recorded</p>
          ) : null}
          {job.status === "running" ? (
            <button
              type="button"
              className="mt-1 text-left text-caption text-muted-foreground underline hover:text-foreground"
              onClick={() => requestOpenLogConsole()}
            >
              Show pipeline log below
            </button>
          ) : null}
          {job.status === "failed" ? (
            <p className="text-muted-foreground">
              Check the pipeline log for the failure stage. Common causes: missing
              Cohere credentials, insufficient notes, or transient model errors —
              retry from the agent&apos;s Dream button after addressing the root cause.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
