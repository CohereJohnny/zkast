"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

import { CompareRunModal } from "@/components/compare-run-modal";
import { useToast } from "@/components/feedback-provider";
import { Button } from "@/components/ui/button";
import { graphHref } from "@/lib/graph-backend";
import { startGraphragIndex } from "@/lib/graphrag-build";
import { useJobEvents } from "@/lib/job-events";
import { fetchTimeoutMessage, fetchWithTimeout, readJsonResponse } from "@/lib/fetch-with-timeout";
import { cn } from "@/lib/utils";

type ComparePayload = {
  graphiti?: { entities?: number; relationships?: number };
  graphrag?: {
    status?: string | null;
    index_id?: string | null;
    entities?: number;
    relationships?: number;
    communities?: number;
    community_reports?: number;
    build_documents?: number;
    ended_at?: string | null;
  };
  corpus_now?: number;
  stale?: boolean;
};

export function MemorySpaceCompareStrip({
  workspaceId,
  agentId,
  compact = false,
}: {
  workspaceId: string;
  agentId?: string | null;
  compact?: boolean;
}) {
  const toast = useToast();
  const { registerActiveJob, requestOpenLogConsole } = useJobEvents();
  const [compare, setCompare] = useState<ComparePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [buildBusy, setBuildBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = agentId ? `?agent_id=${encodeURIComponent(agentId)}` : "";
      const res = await fetchWithTimeout(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/dashboard${qs}`,
        { cache: "no-store", timeoutMs: 15_000 },
      );
      const body = await readJsonResponse<{
        workspace_compare?: ComparePayload;
        selection?: { agent?: { compare?: ComparePayload } };
      }>(res);
      if (!res.ok) {
        setCompare(null);
        setError("Could not load compare metrics");
        return;
      }
      const c = agentId
        ? body.selection?.agent?.compare
        : body.workspace_compare;
      setCompare(c ?? null);
    } catch (err) {
      setCompare(null);
      setError(fetchTimeoutMessage(err));
    } finally {
      setLoading(false);
    }
  }, [workspaceId, agentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const graphragStatus = compare?.graphrag?.status ?? null;
  const graphragBuilding =
    graphragStatus === "pending" || graphragStatus === "running";

  useEffect(() => {
    if (graphragBuilding && !pollRef.current) {
      pollRef.current = setInterval(() => void load(), 5000);
    } else if (!graphragBuilding && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [graphragBuilding, load]);

  const startBuild = useCallback(async () => {
    setBuildBusy(true);
    try {
      const result = await startGraphragIndex(workspaceId, {
        agentId: agentId ?? null,
      });
      if (!result.ok) {
        toast({
          variant: "error",
          message: result.message,
          description: result.description,
        });
        return;
      }
      if (result.jobId) {
        registerActiveJob(result.jobId, workspaceId, agentId ?? null, "graphrag_index");
        requestOpenLogConsole();
      }
      toast({
        variant: "success",
        message:
          graphragStatus === "ready" || graphragStatus === "failed"
            ? "GraphRAG rebuild started"
            : "GraphRAG build started",
      });
      void load();
    } finally {
      setBuildBusy(false);
    }
  }, [
    agentId,
    graphragStatus,
    load,
    registerActiveJob,
    requestOpenLogConsole,
    toast,
    workspaceId,
  ]);

  const g = compare?.graphiti ?? {};
  const r = compare?.graphrag ?? {};
  const buildDocs = r.build_documents ?? 0;
  const corpusNow = compare?.corpus_now ?? 0;
  const buildLabel = buildBusy
    ? "Starting…"
    : graphragBuilding
      ? "Building…"
      : graphragStatus === "ready" || graphragStatus === "failed"
        ? "Rebuild GraphRAG"
        : "Build GraphRAG";

  return (
    <>
      <div
        className={cn(
          "rounded-md border border-border bg-secondary/30 px-3 py-2",
          compact ? "text-caption" : "text-p",
        )}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            {loading ? (
              <span className="text-muted-foreground">Loading compare metrics…</span>
            ) : error ? (
              <span className="flex items-center gap-2 text-destructive">
                {error}
                <button
                  type="button"
                  className="text-primary underline hover:no-underline"
                  onClick={() => void load()}
                >
                  Retry
                </button>
              </span>
            ) : (
              <>
                <span>
                  <span className="font-medium text-foreground">Graphiti</span>{" "}
                  <span className="tabular-nums text-muted-foreground">
                    {g.entities ?? 0} ent · {g.relationships ?? 0} rel
                  </span>
                </span>
                <span>
                  <span className="font-medium text-foreground">GraphRAG</span>{" "}
                  <span className="tabular-nums text-muted-foreground">
                    {r.status === "ready"
                      ? `${r.entities ?? 0} ent · ${r.communities ?? 0} comm · ${r.community_reports ?? 0} reports`
                      : (r.status ?? "not built")}
                  </span>
                </span>
                {buildDocs > 0 || corpusNow > 0 ? (
                  <span className="text-muted-foreground">
                    Built from {buildDocs} docs
                    {r.ended_at ? ` · ${new Date(r.ended_at).toLocaleDateString()}` : ""}
                    {" · "}corpus now {corpusNow}
                    {compare?.stale ? (
                      <span className="ml-1 text-caution">(corpus grew)</span>
                    ) : null}
                  </span>
                ) : null}
              </>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant={
                graphragStatus === "ready" || graphragStatus === "failed"
                  ? "outline"
                  : "default"
              }
              disabled={buildBusy || graphragBuilding}
              onClick={() => void startBuild()}
            >
              {buildLabel}
            </Button>
            <Link
              href={graphHref({ backend: "graphrag", indexId: r.index_id, agentId })}
              className="text-primary hover:underline"
            >
              GraphRAG view
            </Link>
            <Link
              href={`/graph?compare=1${agentId ? `&agent_id=${encodeURIComponent(agentId)}` : ""}`}
              className="text-primary hover:underline"
            >
              Split compare
            </Link>
            <Button size="sm" variant="outline" onClick={() => setModalOpen(true)}>
              Run comparison
            </Button>
          </div>
        </div>
      </div>
      <CompareRunModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        workspaceId={workspaceId}
        agentId={agentId}
      />
    </>
  );
}
