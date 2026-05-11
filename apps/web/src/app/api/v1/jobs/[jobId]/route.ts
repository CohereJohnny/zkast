import { type NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

export async function GET(req: NextRequest, { params }: { params: { jobId: string } }) {
  const { jobId } = params;
  const workspaceId = req.nextUrl.searchParams.get("workspaceId");
  if (!workspaceId || !uuidParam.safeParse(workspaceId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "workspaceId query required" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  const res = await pipelineFetch(`/internal/v1/jobs/${encodeURIComponent(jobId)}`, {
    workspaceId,
    throwOnError: false,
  });
  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
