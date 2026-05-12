import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

const mergeBody = z.object({
  other_entity_id: z.string().uuid(),
  field_selection: z.record(z.string(), z.enum(["survivor", "other"])).optional(),
});

export async function POST(
  req: Request,
  { params }: { params: { workspaceId: string; entityId: string } },
) {
  const { workspaceId, entityId } = params;
  if (!uuidParam.safeParse(workspaceId).success || !uuidParam.safeParse(entityId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid id" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  let json: unknown;
  try {
    json = await req.json();
  } catch {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Expected JSON body" } },
      { status: 400 },
    );
  }
  const parsed = mergeBody.safeParse(json);
  if (!parsed.success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: parsed.error.message } },
      { status: 400 },
    );
  }

  const bodyPayload = {
    ...parsed.data,
    field_selection: parsed.data.field_selection ?? {
      canonical_name: "survivor",
      type: "survivor",
      aliases: "survivor",
      summary: "survivor",
      properties: "survivor",
    },
  };

  const res = await pipelineFetch(
    `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/graph/entities/${encodeURIComponent(entityId)}/merge`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bodyPayload),
      throwOnError: false,
    },
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
