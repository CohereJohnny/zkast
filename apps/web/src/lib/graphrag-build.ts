import { fetchTimeoutMessage, fetchWithTimeout } from "@/lib/fetch-with-timeout";

export function graphragJobId(indexId: string): string {
  return `graphrag:${indexId}`;
}

export type StartGraphragIndexResult =
  | { ok: true; indexId?: string; jobId: string | null }
  | { ok: false; message: string; status: number; description?: string };

export async function startGraphragIndex(
  workspaceId: string,
  opts: { agentId?: string | null; collectionId?: string | null; maxDocs?: number },
): Promise<StartGraphragIndexResult> {
  const base = `/api/v1/workspaces/${encodeURIComponent(workspaceId)}`;
  try {
    const payload: Record<string, unknown> = { max_docs: opts.maxDocs ?? 200 };
    if (opts.collectionId) payload.collection_id = opts.collectionId;
    else if (opts.agentId) payload.agent_id = opts.agentId;
    const res = await fetchWithTimeout(`${base}/graphrag/index`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      timeoutMs: 90_000,
    });
    const body = (await res.json().catch(() => ({}))) as {
      detail?: string;
      error?: { message?: string };
      index_id?: string;
      job_id?: string;
    };
    if (res.status !== 202) {
      return {
        ok: false,
        status: res.status,
        message:
          typeof body?.detail === "string"
            ? body.detail
            : body?.error?.message ?? `Build failed (${res.status})`,
        description:
          res.status === 409
            ? "A stale job may still be registered. Try again — older builds are superseded automatically."
            : undefined,
      };
    }
    const jobId = body.job_id ?? (body.index_id ? graphragJobId(body.index_id) : null);
    return { ok: true, indexId: body.index_id, jobId };
  } catch (err) {
    return {
      ok: false,
      status: 0,
      message: "Could not start GraphRAG build",
      description: fetchTimeoutMessage(err),
    };
  }
}
