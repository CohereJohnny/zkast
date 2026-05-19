import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

const body = z
  .object({
    embedding_model: z.string().min(1).max(80).optional(),
    kinds: z.array(z.enum(["raw_chunk", "note_zettel", "note_amem"])).optional(),
    agent_id: z.string().uuid().optional(),
    limit: z.number().int().min(1).max(5000).optional(),
  })
  .optional();

export async function POST(
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

  let payload: unknown = null;
  try {
    payload = await req.json();
  } catch {
    payload = null;
  }
  const parsed = body.safeParse(payload);
  const forwarded = parsed.success && parsed.data ? parsed.data : {};

  const res = await pipelineFetch(
    `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/retrieval-index/backfill`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(forwarded),
      throwOnError: false,
    },
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
