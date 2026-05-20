"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { readApiErrorMessage } from "@/lib/api-error-message";
import { useJobEvents } from "@/lib/job-events";
import { cn } from "@/lib/utils";

type WikiJob = {
  id: string;
  status: string;
  stats?: Record<string, unknown>;
  failure_reason?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
};

type WikiJobDetail = {
  job: WikiJob;
  mutations: { id: string; mutation_type: string; wiki_page_id: string }[];
};

/**
 * Sprint E — status card for a single wiki generation job.
 *
 * Mirrors `DreamJobStatus`: polls `/wiki-jobs/{id}` while the job is
 * running, surfaces summary stats on terminal status, and offers a
 * one-click way to expand the docked pipeline log.
 */
export function WikiJobStatus({
  workspaceId,
  jobId,
  onDone,
}: {
  workspaceId: string;
  jobId: string | null;
  onDone?: (status: "succeeded" | "failed") => void;
}) {
  const { requestOpenLogConsole } = useJobEvents();
  const [detail, setDetail] = useState<WikiJobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const terminalNotified = useRef(false);

  const load = useCallback(async () => {
    if (!jobId) return;
    try {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/wiki-jobs/${encodeURIComponent(jobId)}`,
        { cache: "no-store" },
      );
      const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        setError(readApiErrorMessage(body, `HTTP ${res.status}`));
        return;
      }
      setDetail(body as unknown as WikiJobDetail);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load wiki job");
    }
  }, [workspaceId, jobId]);

  useEffect(() => {
    if (!jobId) return;
    void load();
    const status = detail?.job?.status;
    if (status === "succeeded" || status === "failed") return;
    const t = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(t);
  }, [jobId, load, detail?.job?.status]);

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
        "rounded-lg border border-border-subtle bg-surface-raised px-3 py-2 text-caption",
        job?.status === "failed" && "border-destructive/40",
      )}
    >
      {error ? <p className="text-destructive">{error}</p> : null}
      {job ? (
        <div className="space-y-1">
          <p className="text-secondary">
            Wiki job{" "}
            <span className="font-mono text-primary">{job.id.slice(0, 8)}…</span> ·{" "}
            <span
              className={cn(
                job.status === "running" && "text-primary",
                job.status === "succeeded" && "text-green-600 dark:text-green-400",
                job.status === "failed" && "text-destructive",
              )}
            >
              {job.status}
            </span>
          </p>
          {terminal && typeof stats === "object" ? (
            <p className="text-muted">
              notes {String(stats.notes_considered ?? 0)} · created{" "}
              {String(stats.pages_created ?? 0)} · updated{" "}
              {String(stats.pages_updated ?? 0)} · citations{" "}
              {String(stats.citations_added ?? 0)} · links{" "}
              {String(stats.links_added ?? 0)}
            </p>
          ) : !terminal ? (
            <p className="text-muted" role="status">
              Compiling pages…
            </p>
          ) : null}
          {job.failure_reason ? (
            <p className="text-destructive">{job.failure_reason}</p>
          ) : null}
          {detail?.mutations?.length ? (
            <p className="text-muted">
              {detail.mutations.length} page mutation(s) recorded
            </p>
          ) : null}
          {job.status === "running" ? (
            <button
              type="button"
              className="mt-1 text-left text-caption text-secondary underline hover:text-primary"
              onClick={() => requestOpenLogConsole()}
            >
              Show pipeline log below
            </button>
          ) : null}
          {job.status === "failed" ? (
            <p className="text-muted">
              Check the pipeline log for the failure stage. Common causes:
              missing model credentials, no atomic notes in scope, or a transient
              database error — retry from the Generate button after addressing
              the root cause.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
