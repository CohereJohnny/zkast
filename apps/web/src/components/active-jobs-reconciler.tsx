"use client";

import { useEffect } from "react";

import { useJobEvents } from "@/lib/job-events";

/** Clears stale localStorage active jobs when the server reports no in-flight work. */
export function ActiveJobsReconciler({ workspaceId }: { workspaceId: string }) {
  const { reconcileActiveJobs } = useJobEvents();

  useEffect(() => {
    void reconcileActiveJobs(workspaceId);
    const t = window.setInterval(() => void reconcileActiveJobs(workspaceId), 30_000);
    return () => window.clearInterval(t);
  }, [workspaceId, reconcileActiveJobs]);

  return null;
}
