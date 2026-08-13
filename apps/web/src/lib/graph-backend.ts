export type GraphBackend = "graphiti" | "graphrag";

const STORAGE_PREFIX = "zkast:graph-backend:";

export function readGraphBackend(workspaceId: string): GraphBackend {
  if (typeof window === "undefined") return "graphiti";
  try {
    const v = localStorage.getItem(`${STORAGE_PREFIX}${workspaceId}`);
    return v === "graphrag" ? "graphrag" : "graphiti";
  } catch {
    return "graphiti";
  }
}

export function writeGraphBackend(workspaceId: string, backend: GraphBackend): void {
  try {
    localStorage.setItem(`${STORAGE_PREFIX}${workspaceId}`, backend);
  } catch {
    /* quota / private mode */
  }
}

/** Map URL `view=graphrag` to backend; `index_id` → graphrag_index_id. */
export function graphBackendFromSearchParams(sp: URLSearchParams): GraphBackend {
  if (sp.get("view") === "graphrag" || sp.get("backend") === "graphrag") return "graphrag";
  return "graphiti";
}

export function graphragIndexIdFromSearchParams(sp: URLSearchParams): string | undefined {
  return sp.get("index_id") ?? sp.get("graphrag_index_id") ?? undefined;
}

export function graphHref(
  opts: {
    backend?: GraphBackend;
    indexId?: string | null;
    agentId?: string | null;
  } = {},
): string {
  const p = new URLSearchParams();
  if (opts.backend === "graphrag") {
    p.set("view", "graphrag");
    if (opts.indexId) p.set("index_id", opts.indexId);
  }
  if (opts.agentId) p.set("agent_id", opts.agentId);
  const qs = p.toString();
  return qs ? `/graph?${qs}` : "/graph";
}
