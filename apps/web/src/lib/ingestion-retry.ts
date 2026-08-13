export type IngestionRetryStage = "parsing" | "generating_notes" | "extracting_graph";

/** Next routes may return `{ error }`; proxied FastAPI uses `{ detail: string | { error?: { message } } }`. */
export function messageFromApiJson(raw: string): string | null {
  try {
    const j = JSON.parse(raw) as Record<string, unknown>;
    const topErr = j.error;
    if (typeof topErr === "object" && topErr !== null && "message" in topErr) {
      const m = (topErr as { message?: unknown }).message;
      if (typeof m === "string" && m.trim()) return m;
    }
    const det = j.detail;
    if (typeof det === "string" && det.trim()) return det;
    if (typeof det === "object" && det !== null) {
      const d = det as Record<string, unknown>;
      const inner = d.error;
      if (typeof inner === "object" && inner !== null && "message" in inner) {
        const m = (inner as { message?: unknown }).message;
        if (typeof m === "string" && m.trim()) return m;
      }
    }
  } catch {
    /* ignore */
  }
  return null;
}

export async function postDocumentIngestionRetry(
  workspaceId: string,
  documentId: string,
  from_stage: IngestionRetryStage,
): Promise<{ ok: true; jobId: string | null } | { ok: false; error: string }> {
  const res = await fetch(
    `/api/v1/workspaces/${workspaceId}/documents/${documentId}/ingestion-runs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ from_stage }),
    },
  );
  const raw = await res.text();
  let j: { job_id?: string } = {};
  try {
    j = JSON.parse(raw) as typeof j;
  } catch {
    /* ignore */
  }
  if (!res.ok) {
    return {
      ok: false,
      error: messageFromApiJson(raw) ?? `Retry failed (${res.status})`,
    };
  }
  return { ok: true, jobId: typeof j.job_id === "string" ? j.job_id : null };
}
