import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

export async function POST(
  _req: Request,
  { params }: { params: { workspaceId: string; spaceId: string } },
) {
  const { workspaceId, spaceId } = params;
  if (!uuidParam.safeParse(workspaceId).success || !uuidParam.safeParse(spaceId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid id" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;
  const res = await pipelineFetch(
    `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/wiki-spaces/${encodeURIComponent(spaceId)}/generate`,
    { method: "POST", throwOnError: false },
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
