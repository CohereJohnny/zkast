import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

export async function GET(
  _req: Request,
  { params }: { params: { workspaceId: string; collectionId: string } },
) {
  const { workspaceId, collectionId } = params;
  if (!uuidParam.safeParse(workspaceId).success || !uuidParam.safeParse(collectionId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid id" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  try {
    const res = await pipelineFetch(
      `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/document-collections/${encodeURIComponent(collectionId)}`,
      { throwOnError: false },
    );
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
    });
  } catch (err) {
    console.error("document-collection get proxy failed", err);
    return NextResponse.json(
      { error: { code: "pipeline_unreachable", message: "Could not reach the pipeline service." } },
      { status: 502 },
    );
  }
}
