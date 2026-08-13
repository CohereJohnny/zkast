"use client";

import { useEffect, useRef } from "react";

import type { ActiveJob } from "@/lib/job-events";

export type JobStreamEvent = {
  type?: string;
  level?: string;
  stage?: string;
  message?: string;
  reason?: string;
  status?: string;
  percent?: number;
  current?: number;
  total?: number;
  name?: string;
  value?: number | string;
  kind?: string;
  label?: string;
  detail?: string;
  data?: Record<string, unknown>;
};

export function useJobStream(
  job: ActiveJob | null,
  {
    replay = true,
    onEvent,
    onTerminal,
  }: {
    replay?: boolean;
    onEvent: (jobId: string, ev: JobStreamEvent) => void;
    onTerminal?: (jobId: string) => void;
  },
) {
  const replayDoneRef = useRef(!replay);
  const jobId = job?.jobId ?? null;
  const workspaceId = job?.workspaceId ?? null;

  useEffect(() => {
    if (!jobId || !workspaceId) return;
    replayDoneRef.current = !replay;
    const qs = new URLSearchParams({ workspaceId });
    if (replay) qs.set("replay", "true");
    else qs.set("replay", "false");
    const url = `/api/v1/jobs/${encodeURIComponent(jobId)}/events?${qs.toString()}`;
    const es = new EventSource(url);
    let closed = false;
    es.onmessage = (msg) => {
      if (closed) return;
      try {
        const ev = JSON.parse(msg.data) as JobStreamEvent;
        if (ev.type === "replay_end") {
          replayDoneRef.current = true;
          return;
        }
        onEvent(jobId, ev);
        if (
          replayDoneRef.current &&
          (ev.type === "job_completed" || ev.type === "job_failed")
        ) {
          closed = true;
          es.close();
          onTerminal?.(jobId);
        }
      } catch {
        /* ignore malformed */
      }
    };
    es.onerror = () => es.close();
    return () => {
      closed = true;
      es.close();
    };
  }, [jobId, workspaceId, replay, onEvent, onTerminal]);
}
