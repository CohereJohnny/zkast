"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { arqEntryJobId, isGraphExtractionJobId } from "@/lib/arq-job-id";
import { type ActiveJob, useActiveJobs } from "@/lib/job-events";
import { emitGraphLiveDelta, parseGraphDeltaFromActivityData } from "@/lib/graph-live-delta";
import { emitPipelineActivity } from "@/lib/pipeline-activity";
import { type JobStreamEvent, useJobStream } from "@/lib/use-job-stream";

function isActiveJobStatus(status: string | undefined): boolean {
  const s = (status ?? "").toLowerCase();
  return s === "running" || s === "queued";
}

function GraphLiveJobWire({
  job,
}: {
  job: ActiveJob;
}) {
  const onEvent = useCallback((jobId: string, ev: JobStreamEvent) => {
    const stage = ev.stage ?? "";

    if (ev.type === "activity" && ev.data) {
      const delta = parseGraphDeltaFromActivityData(ev.data);
      if (delta && (delta.nodes.length > 0 || delta.edges.length > 0)) {
        emitGraphLiveDelta({ ...delta, jobId });
        emitPipelineActivity({
          jobId,
          stage: stage || "extracting_graph",
          graphTouch: true,
        });
      }
    }

    if (
      ev.type === "stage_started" ||
      ev.type === "stage_progress" ||
      ev.type === "stage_completed"
    ) {
      if (stage === "extracting_graph" || stage === "building_graph" || stage === "graphrag_indexing") {
        emitPipelineActivity({ jobId, stage, graphTouch: true });
      }
    }

    if (ev.type === "metric" && ev.name) {
      if (["entity_count", "edge_count", "entities", "relationships"].includes(ev.name)) {
        emitPipelineActivity({
          jobId,
          stage: stage || "extracting_graph",
          graphTouch: true,
        });
      }
    }
  }, []);

  // Live tail only — skip replay so stale job_failed / old batches do not flood the canvas.
  useJobStream(job, { replay: false, onEvent });
  return null;
}

/**
 * Subscribes to every in-flight pipeline job (including ``{id}:graph`` stage jobs
 * that are not always present in the browser's active-job registry).
 */
export function GraphLiveJobBridgeHost({ workspaceId }: { workspaceId: string }) {
  const registered = useActiveJobs();
  const [overviewJobs, setOverviewJobs] = useState<ActiveJob[]>([]);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch(
          `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/jobs/overview`,
          { cache: "no-store" },
        );
        if (!res.ok || cancelled) return;
        const body = (await res.json()) as {
          pipeline_jobs?: Array<{
            job_id?: string;
            status?: string;
            worker_active?: boolean;
            stage?: string;
          }>;
          arq?: { in_progress?: string[] };
        };
        const byId = new Map<string, ActiveJob>();
        for (const row of body.pipeline_jobs ?? []) {
          const jobId = row.job_id;
          if (!jobId) continue;
          if (!isActiveJobStatus(row.status) && !row.worker_active) continue;
          byId.set(jobId, {
            jobId,
            workspaceId,
            documentId: null,
            kind: jobId.endsWith(":graph")
              ? "extract_graph"
              : jobId.startsWith("graphrag:")
                ? "graphrag_index"
                : null,
            startedAt: Date.now(),
          });
        }
        for (const entry of body.arq?.in_progress ?? []) {
          const jobId = arqEntryJobId(entry);
          if (!jobId || jobId.startsWith("cron:") || byId.has(jobId)) continue;
          byId.set(jobId, {
            jobId,
            workspaceId,
            documentId: null,
            kind: isGraphExtractionJobId(jobId) ? "extract_graph" : null,
            startedAt: Date.now(),
          });
        }
        if (!cancelled) setOverviewJobs(Array.from(byId.values()));
      } catch {
        /* offline */
      }
    };
    void poll();
    const t = window.setInterval(() => void poll(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [workspaceId]);

  const bridgeJobs = useMemo(() => {
    const map = new Map<string, ActiveJob>();
    for (const j of registered) map.set(j.jobId, j);
    for (const j of overviewJobs) map.set(j.jobId, j);
    return Array.from(map.values());
  }, [registered, overviewJobs]);

  if (bridgeJobs.length === 0) return null;

  return (
    <>
      {bridgeJobs.map((job) => (
        <GraphLiveJobWire key={job.jobId} job={job} />
      ))}
    </>
  );
}
