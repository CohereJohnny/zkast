import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

export async function GET(
  _req: Request,
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

  try {
    const res = await pipelineFetch(
      `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/north/agents`,
      { throwOnError: false },
    );
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
    });
  } catch (err) {
    console.error("north agents list proxy failed", err);
    return NextResponse.json(
      {
        error: {
          code: "pipeline_unreachable",
          message:
            err instanceof Error
              ? err.message
              : "Could not reach the pipeline service. Is it running and is PIPELINE_INTERNAL_URL set?",
        },
      },
      { status: 502 },
    );
  }
}
