"use client";

import { useEffect } from "react";

const EVENT_NAME = "zkast:graph-live-delta";

export type GraphLiveNode = {
  id: string;
  name: string;
  type: string;
};

export type GraphLiveEdge = {
  id: string;
  source: string;
  target: string;
  type?: string;
};

export type GraphLiveDelta = {
  nodes: GraphLiveNode[];
  edges: GraphLiveEdge[];
  jobId?: string;
};

export function emitGraphLiveDelta(delta: GraphLiveDelta): void {
  if (typeof window === "undefined") return;
  if (!delta.nodes.length && !delta.edges.length) return;
  window.dispatchEvent(new CustomEvent<GraphLiveDelta>(EVENT_NAME, { detail: delta }));
}

export function useGraphLiveDelta(handler: (delta: GraphLiveDelta) => void): void {
  useEffect(() => {
    if (typeof window === "undefined") return;
    const fn = (e: Event) => {
      const ce = e as CustomEvent<GraphLiveDelta>;
      const detail = ce.detail;
      if (!detail) return;
      handler(detail);
    };
    window.addEventListener(EVENT_NAME, fn);
    return () => window.removeEventListener(EVENT_NAME, fn);
  }, [handler]);
}

export function parseGraphDeltaFromActivityData(
  data: Record<string, unknown> | undefined,
): GraphLiveDelta | null {
  if (!data) return null;
  const rawNodes = data.nodes;
  const rawEdges = data.edges;
  const nodes: GraphLiveNode[] = [];
  const edges: GraphLiveEdge[] = [];

  if (Array.isArray(rawNodes)) {
    for (const n of rawNodes) {
      if (!n || typeof n !== "object") continue;
      const row = n as Record<string, unknown>;
      const id = typeof row.id === "string" ? row.id : "";
      const name = typeof row.name === "string" ? row.name : "";
      const type = typeof row.type === "string" ? row.type : "Concept";
      if (id && name) nodes.push({ id, name, type });
    }
  }
  if (Array.isArray(rawEdges)) {
    for (const e of rawEdges) {
      if (!e || typeof e !== "object") continue;
      const row = e as Record<string, unknown>;
      const id = typeof row.id === "string" ? row.id : "";
      const source = typeof row.source === "string" ? row.source : "";
      const target = typeof row.target === "string" ? row.target : "";
      if (!id || !source || !target) continue;
      edges.push({
        id,
        source,
        target,
        type: typeof row.type === "string" ? row.type : undefined,
      });
    }
  }
  if (!nodes.length && !edges.length) return null;
  return { nodes, edges };
}
