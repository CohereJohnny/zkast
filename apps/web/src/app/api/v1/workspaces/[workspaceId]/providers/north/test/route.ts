import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

export async function POST(
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
      `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/north/test-connection`,
      { method: "POST", throwOnError: false },
    );
    const payload: unknown = await res.json().catch(() => ({}));
    return NextResponse.json(payload, { status: res.ok ? 200 : res.status });
  } catch (err) {
    console.error("north test proxy failed", err);
    return NextResponse.json(
      {
        error: {
          code: "internal_error",
          message: err instanceof Error ? err.message : "Pipeline request failed",
        },
      },
      { status: 502 },
    );
  }
}
