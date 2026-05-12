import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

const mergeBody = z.object({
  other_note_id: z.string().uuid(),
  field_selection: z
    .object({
      title: z.enum(["survivor", "other"]).optional(),
      body: z.enum(["survivor", "other"]).optional(),
      tags: z.enum(["survivor", "other"]).optional(),
    })
    .optional(),
});

export async function POST(
  req: Request,
  { params }: { params: { workspaceId: string; noteId: string } },
) {
  const { workspaceId, noteId } = params;
  if (!uuidParam.safeParse(workspaceId).success || !uuidParam.safeParse(noteId).success) {
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

  const res = await pipelineFetch(
    `/internal/v1/notes/${encodeURIComponent(noteId)}/merge?workspace_id=${encodeURIComponent(workspaceId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(parsed.data),
      throwOnError: false,
    },
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
