import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

export async function GET(
  req: NextRequest,
  { params }: { params: { workspaceId: string } },
) {
  const { workspaceId } = params;
  if (!uuidParam.safeParse(workspaceId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid workspace id" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  const url = new URL(req.url);
  const agentId = url.searchParams.get("agent_id");
  const conversationId = url.searchParams.get("conversation_id");
  const qs = new URLSearchParams();
  if (agentId && uuidParam.safeParse(agentId).success) {
    qs.set("agent_id", agentId);
  }
  if (conversationId) {
    qs.set("conversation_id", conversationId);
  }
  const suffix = qs.toString() ? `?${qs.toString()}` : "";

  const res = await pipelineFetch(
    `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/dashboard${suffix}`,
    { method: "GET", throwOnError: false },
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
