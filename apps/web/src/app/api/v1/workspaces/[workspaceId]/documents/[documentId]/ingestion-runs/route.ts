import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

const retryBody = z.object({
  from_stage: z.enum(["parsing", "generating_notes", "extracting_graph"]).default("parsing"),
});

export async function POST(
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

  let json: unknown = {};
  try {
    if (req.headers.get("content-type")?.includes("application/json")) {
      json = await req.json();
    }
  } catch {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid JSON body" } },
      { status: 400 },
    );
  }

  const parsed = retryBody.safeParse(json);
  if (!parsed.success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: parsed.error.message } },
      { status: 400 },
    );
  }

  const res = await pipelineFetch("/internal/v1/ingestion-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      document_id: documentId,
      from_stage: parsed.data.from_stage,
    }),
    throwOnError: false,
  });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
