"use client";

import { useCallback, useEffect, useState } from "react";

import { useToast } from "@/components/feedback-provider";
import {
  postDocumentIngestionRetry,
  type IngestionRetryStage,
} from "@/lib/ingestion-retry";
import { useJobEvents } from "@/lib/job-events";

const STAGES: { stage: IngestionRetryStage; label: string }[] = [
  { stage: "parsing", label: "Parsing" },
  { stage: "generating_notes", label: "Notes" },
  { stage: "extracting_graph", label: "Graph" },
];

const ACTIVE_STATUSES = new Set([
  "queued",
  "parsing",
  "generating_notes",
  "extracting_graph",
  "building_graph",
]);

const BULK_CONCURRENCY = 3;

type DocRow = { id: string; status: string };

/** Retry pipeline stages for every imported thread document on a Slack channel. */
export function SlackChannelRetryButtons({
  workspaceId,
  sourceId,
  channelName,
  imported,
  onBulkComplete,
}: {
  workspaceId: string;
  sourceId: string;
  channelName?: string;
  imported: boolean;
  onBulkComplete?: () => void;
}) {
  const toast = useToast();
  const { registerActiveJob, requestOpenLogConsole, reconcileActiveJobs } = useJobEvents();
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [retryBusy, setRetryBusy] = useState<IngestionRetryStage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadDocs = useCallback(async () => {
    if (!imported) {
      setDocs([]);
      return;
    }
    setLoading(true);
    try {
      const qs = new URLSearchParams({
        source_kind: "slack_conversation",
        agent_id: sourceId,
      });
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/documents?${qs.toString()}`, {
        cache: "no-store",
      });
      const body = (await res.json()) as { items?: DocRow[] };
      setDocs(body.items ?? []);
    } catch {
      setDocs([]);
    } finally {
      setLoading(false);
    }
  }, [workspaceId, sourceId, imported]);

  useEffect(() => {
    void loadDocs();
  }, [loadDocs]);

  if (!imported) return null;

  const eligible = docs.filter((d) => !ACTIVE_STATUSES.has(d.status));

  const postBulkRetry = async (from_stage: IngestionRetryStage) => {
    if (eligible.length === 0) {
      setError("No imported threads to retry — run Import first.");
      return;
    }
    const label = STAGES.find((s) => s.stage === from_stage)?.label ?? from_stage;
    const ch = channelName ? `#${channelName}` : "this channel";
    toast({
      message: `Queueing ${label} for ${eligible.length} thread${eligible.length === 1 ? "" : "s"}`,
      description: `${ch} — ${eligible.length} background job${eligible.length === 1 ? "" : "s"}; watch the pipeline log below.`,
    });
    setError(null);
    setRetryBusy(from_stage);
    let queued = 0;
    const failures: string[] = [];
    const jobKind =
      from_stage === "extracting_graph"
        ? "extract_graph"
        : from_stage === "generating_notes"
          ? "generate_atomic_notes"
          : "document_parse";

    try {
      let index = 0;
      const workers = Array.from({ length: Math.min(BULK_CONCURRENCY, eligible.length) }, async () => {
        while (index < eligible.length) {
          const doc = eligible[index];
          index += 1;
          if (!doc) continue;
          const result = await postDocumentIngestionRetry(workspaceId, doc.id, from_stage);
          if (!result.ok) {
            failures.push(result.error);
            continue;
          }
          queued += 1;
          if (result.jobId) {
            registerActiveJob(result.jobId, workspaceId, doc.id, jobKind);
          }
        }
      });
      await Promise.all(workers);

      if (queued > 0) {
        requestOpenLogConsole();
        toast({
          variant: "success",
          message: `${label} retry queued for ${queued} thread${queued === 1 ? "" : "s"}`,
        });
      }
      if (failures.length > 0) {
        setError(failures[0] ?? "Some retries failed");
      }
      void loadDocs();
      onBulkComplete?.();
      window.setTimeout(() => void reconcileActiveJobs(workspaceId), 5000);
    } finally {
      setRetryBusy(null);
    }
  };

  return (
    <div className="mt-2 space-y-1">
      <p className="text-caption font-medium text-muted-foreground">Retry from stage</p>
      <p className="text-caption text-muted-foreground/90">
        {loading
          ? "Loading imported threads…"
          : eligible.length > 0
            ? `Applies to ${eligible.length} imported thread${eligible.length === 1 ? "" : "s"}.`
            : "No idle thread documents — import or wait for active jobs to finish."}
      </p>
      {error ? (
        <p className="text-caption text-red-300" role="alert">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {STAGES.map(({ stage, label }) => (
          <button
            key={stage}
            type="button"
            disabled={loading || retryBusy !== null || eligible.length === 0}
            className="rounded-md border border-input px-2 py-1 text-caption text-muted-foreground hover:bg-secondary disabled:opacity-50"
            onClick={() => void postBulkRetry(stage)}
          >
            {retryBusy === stage ? "…" : label}
          </button>
        ))}
      </div>
    </div>
  );
}
