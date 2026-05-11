import type { NextRequest } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

export async function GET(req: NextRequest, { params }: { params: { jobId: string } }) {
  const { jobId } = params;
  const workspaceId = req.nextUrl.searchParams.get("workspaceId");
  if (!workspaceId || !uuidParam.safeParse(workspaceId).success) {
    return new Response(
      JSON.stringify({
        error: { code: "validation_failed", message: "workspaceId query required" },
      }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  const res = await pipelineFetch(`/internal/v1/jobs/${encodeURIComponent(jobId)}/events`, {
    workspaceId,
    throwOnError: false,
  });

  if (!res.ok) {
    const body = await res.text();
    return new Response(body, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
    });
  }

  return new Response(res.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
