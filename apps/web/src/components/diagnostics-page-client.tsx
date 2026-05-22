"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useConfirm, useToast } from "@/components/feedback-provider";

type StalledDoc = {
  document_id: string;
  workspace_id: string;
  status: string;
  ingestion_run_id: string | null;
  last_heartbeat_at: string | null;
  updated_at: string | null;
};

type StageLatency = {
  status: string;
  p50_seconds: number | null;
  p95_seconds: number | null;
  n: number;
};

type Diagnostics = {
  arq: { queue_depth: number | null; in_progress: string[] };
  stalled_documents: StalledDoc[];
  stage_latency: StageLatency[];
  job_hashes: { terminal: number; active: number };
};

function formatSeconds(s: number | null): string {
  if (s == null || Number.isNaN(s)) return "—";
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = s - m * 60;
  return `${m}m ${rem.toFixed(0)}s`;
}

export function DiagnosticsPageClient({ workspaceId }: { workspaceId: string }) {
  const [data, setData] = useState<Diagnostics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cleanupBusy, setCleanupBusy] = useState(false);
  const [indexStatus, setIndexStatus] = useState<{
    raw_chunk?: { indexed?: number; total?: number };
    by_kind?: Record<string, number>;
  } | null>(null);
  const [indexBusy, setIndexBusy] = useState<string | null>(null);
  const [indexError, setIndexError] = useState<string | null>(null);

  const toast = useToast();
  const confirm = useConfirm();

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(
        `/api/v1/admin/diagnostics?workspace_id=${encodeURIComponent(workspaceId)}`,
        { cache: "no-store" },
      );
      const body = (await res.json()) as Diagnostics & { error?: { message?: string } };
      if (!res.ok) {
        setError(body.error?.message ?? "Failed to load diagnostics");
        return;
      }
      setData(body);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  const loadIndexStatus = useCallback(async () => {
    setIndexError(null);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/retrieval-index/status`,
        { cache: "no-store" },
      );
      const body = (await res.json()) as {
        raw_chunk?: { indexed?: number; total?: number };
        by_kind?: Record<string, number>;
        error?: { message?: string };
      };
      if (!res.ok) {
        setIndexError(body.error?.message ?? "Failed to load index status");
        return;
      }
      setIndexStatus(body);
    } catch {
      setIndexError("Failed to load index status");
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
    void loadIndexStatus();
    const t = window.setInterval(() => {
      void load();
      void loadIndexStatus();
    }, 8000);
    return () => window.clearInterval(t);
  }, [load, loadIndexStatus]);

  const runBackfill = useCallback(
    async (kinds: string[]) => {
      setIndexBusy(kinds.join(","));
      setIndexError(null);
      try {
        const res = await fetch(
          `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/retrieval-index/backfill`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ kinds }),
          },
        );
        const body = (await res.json()) as { error?: { message?: string } };
        if (!res.ok) {
          setIndexError(body.error?.message ?? "Backfill failed");
          toast({ variant: "error", message: "Backfill failed" });
          return;
        }
        toast({ variant: "success", message: `Backfill started: ${kinds.join(", ")}` });
        await loadIndexStatus();
      } catch {
        setIndexError("Backfill request failed");
        toast({ variant: "error", message: "Backfill request failed" });
      } finally {
        setIndexBusy(null);
      }
    },
    [workspaceId, toast, loadIndexStatus],
  );

  const cleanupHashes = useCallback(async () => {
    const ok = await confirm({
      title: "Clean terminal job hashes?",
      description:
        "Removes only Redis job hashes whose status is succeeded / failed / cancelled. Active ingestions are not touched.",
      confirmLabel: "Clean",
      variant: "danger",
    });
    if (!ok) return;
    setCleanupBusy(true);
    try {
      const res = await fetch(`/api/v1/admin/cleanup-stale-job-hashes`, {
        method: "POST",
      });
      const body = (await res.json()) as { deleted?: number; skipped_active?: number };
      if (!res.ok) {
        toast({ variant: "error", message: "Cleanup failed" });
        return;
      }
      toast({
        variant: "success",
        message: `Cleaned ${body.deleted ?? 0} hashes`,
        description:
          body.skipped_active && body.skipped_active > 0
            ? `Skipped ${body.skipped_active} active.`
            : undefined,
      });
      void load();
    } finally {
      setCleanupBusy(false);
    }
  }, [confirm, toast, load]);

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-h4 text-muted-foreground">Diagnostics</h1>
          <p className="mt-1 text-p text-muted-foreground">
            Pipeline health snapshot. Refreshes every 8 seconds.
          </p>
        </div>
        <Link
          href="/settings"
          className="rounded-md border border-input px-3 py-1.5 text-caption text-muted-foreground transition-colors duration-150 hover:bg-secondary"
        >
          Back to settings
        </Link>
      </header>

      {error ? (
        <p role="alert" className="text-caption text-red-300">
          {error}
        </p>
      ) : null}
      {loading && !data ? <p className="text-caption text-muted-foreground">Loading…</p> : null}

      {data ? (
        <>
          <section
            aria-label="arq queue"
            className="rounded-lg border border-border bg-card/80 p-4"
          >
            <h2 className="text-h5 text-muted-foreground">arq queue</h2>
            <dl className="mt-2 grid grid-cols-2 gap-2 text-caption text-muted-foreground">
              <dt>Queue depth</dt>
              <dd className="text-muted-foreground">{data.arq.queue_depth ?? "n/a"}</dd>
              <dt>In-progress</dt>
              <dd className="text-muted-foreground">
                {data.arq.in_progress.length === 0
                  ? "—"
                  : data.arq.in_progress.map((s) => s.slice(0, 24)).join(", ")}
              </dd>
            </dl>
          </section>

          <section
            aria-label="Stalled documents"
            className="rounded-lg border border-border bg-card/80 p-4"
          >
            <h2 className="text-h5 text-muted-foreground">Stalled documents</h2>
            <p className="mt-1 text-caption text-muted-foreground">
              Documents in an active status whose ingestion heartbeat is older than 90s.
              The worker reconciler will mark these failed within ~1 minute.
            </p>
            {data.stalled_documents.length === 0 ? (
              <p className="mt-3 text-caption text-muted-foreground">None.</p>
            ) : (
              <ul className="mt-3 divide-y divide-border-subtle text-caption">
                {data.stalled_documents.map((d) => (
                  <li key={d.document_id} className="py-2">
                    <p className="font-mono text-muted-foreground">{d.document_id}</p>
                    <p className="text-muted-foreground">
                      status={d.status} · run={d.ingestion_run_id ?? "—"} · heartbeat=
                      {d.last_heartbeat_at ?? "never"}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section
            aria-label="Stage latency"
            className="rounded-lg border border-border bg-card/80 p-4"
          >
            <h2 className="text-h5 text-muted-foreground">Stage latency (24h)</h2>
            {data.stage_latency.length === 0 ? (
              <p className="mt-2 text-caption text-muted-foreground">No completed runs in the last 24h.</p>
            ) : (
              <table className="mt-2 w-full text-caption">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="text-left">Status</th>
                    <th className="text-right">P50</th>
                    <th className="text-right">P95</th>
                    <th className="text-right">N</th>
                  </tr>
                </thead>
                <tbody className="text-muted-foreground">
                  {data.stage_latency.map((row) => (
                    <tr key={row.status}>
                      <td>{row.status}</td>
                      <td className="text-right font-mono">{formatSeconds(row.p50_seconds)}</td>
                      <td className="text-right font-mono">{formatSeconds(row.p95_seconds)}</td>
                      <td className="text-right font-mono">{row.n}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section
            aria-label="Retrieval indexes"
            className="rounded-lg border border-border bg-card/80 p-4"
          >
            <h2 className="text-h5 text-muted-foreground">Retrieval indexes</h2>
            <p className="mt-1 text-caption text-muted-foreground">
              Embedding counts for naive RAG chunks and note indexes (Zettel + A-MEM).
            </p>
            {indexError ? (
              <p className="mt-2 text-caption text-red-300" role="alert">
                {indexError}
              </p>
            ) : null}
            {indexStatus ? (
              <dl className="mt-2 grid grid-cols-2 gap-2 text-caption text-muted-foreground">
                <dt>Raw chunks indexed</dt>
                <dd className="text-muted-foreground">
                  {indexStatus.raw_chunk?.indexed ?? "—"} / {indexStatus.raw_chunk?.total ?? "—"}
                </dd>
                <dt>note_zettel</dt>
                <dd className="text-muted-foreground">{indexStatus.by_kind?.note_zettel ?? 0}</dd>
                <dt>note_amem</dt>
                <dd className="text-muted-foreground">{indexStatus.by_kind?.note_amem ?? 0}</dd>
              </dl>
            ) : (
              <p className="mt-2 text-caption text-muted-foreground">Loading index status…</p>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={indexBusy !== null}
                onClick={() => void runBackfill(["raw_chunk"])}
                className="rounded-md border border-input px-3 py-1.5 text-caption text-muted-foreground hover:bg-secondary disabled:opacity-50"
              >
                {indexBusy === "raw_chunk" ? "Running…" : "Backfill raw chunks"}
              </button>
              <button
                type="button"
                disabled={indexBusy !== null}
                onClick={() => void runBackfill(["note_zettel", "note_amem"])}
                className="rounded-md border border-input px-3 py-1.5 text-caption text-muted-foreground hover:bg-secondary disabled:opacity-50"
              >
                {indexBusy === "note_zettel,note_amem" ? "Running…" : "Backfill note indexes"}
              </button>
            </div>
          </section>

          <section
            aria-label="Job hash hygiene"
            className="rounded-lg border border-border bg-card/80 p-4"
          >
            <h2 className="text-h5 text-muted-foreground">Job hash hygiene</h2>
            <dl className="mt-2 grid grid-cols-2 gap-2 text-caption text-muted-foreground">
              <dt>Terminal hashes (cleanable)</dt>
              <dd className="text-muted-foreground">{data.job_hashes.terminal}</dd>
              <dt>Active hashes</dt>
              <dd className="text-muted-foreground">{data.job_hashes.active}</dd>
            </dl>
            <div className="mt-3 flex justify-end">
              <button
                type="button"
                disabled={cleanupBusy || data.job_hashes.terminal === 0}
                onClick={() => void cleanupHashes()}
                className="rounded-md border border-input px-3 py-1.5 text-caption text-muted-foreground transition-colors duration-150 hover:bg-secondary disabled:opacity-50"
              >
                {cleanupBusy ? "Cleaning…" : "Clean terminal hashes"}
              </button>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
