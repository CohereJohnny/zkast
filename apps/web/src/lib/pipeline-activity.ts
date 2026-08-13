"use client";

import { useEffect } from "react";

const EVENT_NAME = "zkast:pipeline-activity";

export type PipelineActivityPayload = {
  jobId?: string;
  stage?: string;
  kind?: string;
  metrics?: {
    entities?: number;
    edges?: number;
    notes?: number;
    tokens?: number;
  };
  /** When true, graph listeners should refetch (subject to throttling). */
  graphTouch?: boolean;
};

export function emitPipelineActivity(payload: PipelineActivityPayload): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<PipelineActivityPayload>(EVENT_NAME, { detail: payload }));
}

export function usePipelineActivity(handler: (payload: PipelineActivityPayload) => void): void {
  useEffect(() => {
    if (typeof window === "undefined") return;
    const fn = (e: Event) => {
      const ce = e as CustomEvent<PipelineActivityPayload>;
      handler(ce.detail ?? {});
    };
    window.addEventListener(EVENT_NAME, fn);
    return () => window.removeEventListener(EVENT_NAME, fn);
  }, [handler]);
}
