import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();
// Static `cohere` and `north` test routes take precedence over this dynamic
// segment in Next.js, so this handles openai / azure_openai (and any future
// registry provider).
const providerParam = z.enum(["openai", "azure_openai", "cohere_compat"]);

export async function POST(
  _req: Request,
  { params }: { params: { workspaceId: string; provider: string } },
) {
  const { workspaceId, provider } = params;
  if (!uuidParam.safeParse(workspaceId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid workspaceId" } },
      { status: 400 },
    );
  }
  if (!providerParam.safeParse(provider).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Unknown provider" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;
  const res = await pipelineFetch(
    `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/providers/${encodeURIComponent(provider)}/test`,
    { method: "POST", throwOnError: false },
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
