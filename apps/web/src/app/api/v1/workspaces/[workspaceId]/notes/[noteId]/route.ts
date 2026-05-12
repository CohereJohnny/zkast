import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

const patchBody = z.object({
  title: z.string().min(1).max(200).optional(),
  body: z.string().max(10000).optional(),
  tags: z.array(z.string()).optional(),
});

export async function GET(
  _req: Request,
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

  const res = await pipelineFetch(
    `/internal/v1/notes/${encodeURIComponent(noteId)}?workspace_id=${encodeURIComponent(workspaceId)}`,
    { method: "GET", throwOnError: false },
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}

export async function PATCH(
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

  const parsed = patchBody.safeParse(json);
  if (!parsed.success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: parsed.error.message } },
      { status: 400 },
    );
  }

  const res = await pipelineFetch(
    `/internal/v1/notes/${encodeURIComponent(noteId)}?workspace_id=${encodeURIComponent(workspaceId)}`,
    {
      method: "PATCH",
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

export async function DELETE(
  _req: Request,
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

  const res = await pipelineFetch(
    `/internal/v1/notes/${encodeURIComponent(noteId)}?workspace_id=${encodeURIComponent(workspaceId)}`,
    { method: "DELETE", throwOnError: false },
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
