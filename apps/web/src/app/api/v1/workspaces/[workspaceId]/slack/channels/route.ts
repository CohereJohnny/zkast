import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

export async function GET(
  req: Request,
  { params }: { params: { workspaceId: string } },
) {
  const { workspaceId } = params;
  if (!uuidParam.safeParse(workspaceId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid workspaceId" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;
  const refresh = new URL(req.url).searchParams.get("refresh") === "true";
  const res = await pipelineFetch(
    `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/slack/channels${refresh ? "?refresh=true" : ""}`,
    { method: "GET", throwOnError: false },
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
