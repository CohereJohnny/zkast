import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

export async function GET(
  req: Request,
  { params }: { params: { workspaceId: string; documentId: string } },
) {
  const { workspaceId, documentId } = params;
  if (!uuidParam.safeParse(workspaceId).success || !uuidParam.safeParse(documentId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid id" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  const url = new URL(req.url);
  const cascade = url.searchParams.get("cascade") ?? "exclusive_derivatives";

  const path =
    `/internal/v1/documents/${encodeURIComponent(documentId)}/delete-preview` +
    `?workspace_id=${encodeURIComponent(workspaceId)}&cascade=${encodeURIComponent(cascade)}`;

  const res = await pipelineFetch(path, { method: "GET", throwOnError: false });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
