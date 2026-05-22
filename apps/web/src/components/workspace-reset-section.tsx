"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { useConfirm, useToast } from "@/components/feedback-provider";
import { readApiErrorMessage } from "@/lib/api-error-message";

type ResetPreview = {
  workspace_id: string;
  busy: boolean;
  busy_reasons: string[];
  counts: Record<string, number>;
};

export function WorkspaceResetSection({ workspaceId }: { workspaceId: string }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [preview, setPreview] = useState<ResetPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [resetBusy, setResetBusy] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [force, setForce] = useState(false);

  const loadPreview = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/reset/preview`,
        { cache: "no-store" },
      );
      const body = (await res.json()) as ResetPreview & {
        error?: { message?: string };
        detail?: unknown;
      };
      if (!res.ok) {
        toast({
          variant: "error",
          message: readApiErrorMessage(body, "Failed to load reset preview"),
        });
        return;
      }
      setPreview(body);
    } finally {
      setLoading(false);
    }
  }, [workspaceId, toast]);

  useEffect(() => {
    void loadPreview();
  }, [loadPreview]);

  const totalRows = preview
    ? Object.values(preview.counts).reduce((a, b) => a + b, 0)
    : 0;

  const runReset = async () => {
    if (confirmText.trim() !== "RESET") {
      toast({
        variant: "error",
        message: 'Type RESET in the confirmation box to proceed.',
      });
      return;
    }
    const ok = await confirm({
      title: "Reset workspace to baseline?",
      description:
        "This permanently deletes all documents, notes, graph rows, chat history, eval runs, wiki, dream jobs, North cache, retrieval indexes, Redis job telemetry, FalkorDB graph data, and stored files. API keys and pipeline settings are kept.",
      confirmLabel: "Wipe everything",
      cancelLabel: "Cancel",
      variant: "danger",
    });
    if (!ok) return;

    setResetBusy(true);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/reset`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            confirm: "RESET",
            force,
            purge_graphiti: true,
            purge_storage: true,
            purge_redis_jobs: true,
          }),
        },
      );
      const body = (await res.json()) as {
        postgres?: Record<string, number>;
        error?: { message?: string };
        detail?: unknown;
      };
      if (!res.ok) {
        toast({
          variant: "error",
          message: readApiErrorMessage(body, "Workspace reset failed"),
        });
        return;
      }
      const deleted = Object.values(body.postgres ?? {}).reduce((a, b) => a + b, 0);
      toast({
        variant: "success",
        message: "Workspace reset to baseline",
        description: `Removed ${deleted} database rows. Re-ingest sources, then run evals.`,
      });
      setConfirmText("");
      await loadPreview();
    } finally {
      setResetBusy(false);
    }
  };

  return (
    <section
      className="rounded-lg border border-[color:var(--semantic-danger)]/40 bg-surface p-5"
      aria-labelledby="reset-title"
    >
      <h2
        id="reset-title"
        className="flex items-center gap-2 text-title-3 text-[color:var(--semantic-danger)]"
      >
        <AlertTriangle className="h-5 w-5 shrink-0" strokeWidth={1.5} aria-hidden />
        Baseline reset
      </h2>
      <p className="mt-2 text-body text-secondary">
        Return this workspace to an empty slate for controlled end-to-end testing: no
        sources, notes, graph, jobs, chat, evals, or wiki. Keeps workspace settings and API
        keys.
      </p>

      {loading ? (
        <p className="mt-4 text-caption text-muted">Loading preview…</p>
      ) : preview ? (
        <div className="mt-4 space-y-3">
          {preview.busy ? (
            <div
              className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-caption text-secondary"
              role="status"
            >
              <p className="font-medium text-primary">Active work detected</p>
              <ul className="mt-1 list-inside list-disc">
                {preview.busy_reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
              <label className="mt-2 flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={force}
                  onChange={(e) => setForce(e.target.checked)}
                  className="rounded border-border-subtle"
                />
                <span>Force cancel active jobs and reset anyway</span>
              </label>
            </div>
          ) : null}

          <dl className="grid grid-cols-2 gap-2 text-caption sm:grid-cols-3">
            {Object.entries(preview.counts)
              .filter(([, n]) => n > 0)
              .map(([key, n]) => (
                <div key={key} className="rounded-md bg-surface-raised px-2 py-1.5">
                  <dt className="text-muted">{key.replace(/_/g, " ")}</dt>
                  <dd className="font-mono text-primary">{n}</dd>
                </div>
              ))}
          </dl>
          {totalRows === 0 ? (
            <p className="text-caption text-muted">Workspace content is already empty.</p>
          ) : null}
        </div>
      ) : null}

      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
        <label className="flex flex-1 flex-col gap-1 text-caption text-muted">
          Type RESET to confirm
          <input
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="RESET"
            autoComplete="off"
            className="rounded-md border border-border-subtle bg-surface-raised px-2 py-1.5 font-mono text-body text-primary"
          />
        </label>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={resetBusy || loading}
            onClick={() => void loadPreview()}
            className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-border-subtle px-3 py-2 text-body text-secondary transition hover:bg-surface-raised disabled:opacity-50"
          >
            <RefreshCw className="h-4 w-4" aria-hidden />
            Refresh
          </button>
          <button
            type="button"
            disabled={resetBusy || loading || (preview?.busy && !force)}
            onClick={() => void runReset()}
            className="rounded-md bg-[color:var(--semantic-danger)] px-4 py-2 text-body font-medium text-white transition hover:opacity-90 disabled:opacity-50"
          >
            {resetBusy ? "Resetting…" : "Reset to baseline"}
          </button>
        </div>
      </div>

      <p className="mt-3 text-caption text-muted">
        Suggested rebuild path: upload or import sources → wait for notes/graph → optional
        dream/wiki → backfill retrieval index (Diagnostics) → run evals. Use{" "}
        <span className="font-mono text-secondary">oil_gas_v1</span> after the Oil &amp; Gas PDF
        fixture; use <span className="font-mono text-secondary">memory_locomo_lite_v1</span> only
        after you have ingested North/PDF content. If Graph eval still shows stale contexts, run
        reset again (FalkorDB must be reachable).
      </p>
    </section>
  );
}
