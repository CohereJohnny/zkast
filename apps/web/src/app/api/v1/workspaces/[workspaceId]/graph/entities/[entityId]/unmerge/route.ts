import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

/**
 * Restore the most recently merged victim entity from the audit log.
 *
 * Body is empty — the audit row (`merge_audit_log`) already captures the
 * pre-merge survivor + victim state, so the caller only needs to identify
 * which survivor entity to roll back.
 */
export async function POST(
  _req: Request,
  { params }: { params: { workspaceId: string; entityId: string } },
) {
  const { workspaceId, entityId } = params;
  if (!uuidParam.safeParse(workspaceId).success || !uuidParam.safeParse(entityId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid id" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  const res = await pipelineFetch(
    `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/graph/entities/${encodeURIComponent(entityId)}/unmerge`,
    { method: "POST", throwOnError: false },
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
