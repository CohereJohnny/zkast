import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

const patchBody = z.object({
  title: z.string().max(200).optional(),
  scope: z.record(z.string(), z.unknown()).optional(),
  model_settings: z.record(z.string(), z.unknown()).optional(),
  pinned_snapshot_id: z.string().uuid().nullable().optional(),
});

function validate(workspaceId: string, sessionId: string) {
  if (
    !uuidParam.safeParse(workspaceId).success ||
    !uuidParam.safeParse(sessionId).success
  ) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid id" } },
      { status: 400 },
    );
  }
  return null;
}

export async function GET(
  req: Request,
  { params }: { params: { workspaceId: string; sessionId: string } },
) {
  const { workspaceId, sessionId } = params;
  const bad = validate(workspaceId, sessionId);
  if (bad) return bad;
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  const url = new URL(req.url);
  const qs = url.searchParams.toString();
  const path = `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/chat-sessions/${encodeURIComponent(sessionId)}${qs ? `?${qs}` : ""}`;

  const res = await pipelineFetch(path, { method: "GET", throwOnError: false });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}

export async function PATCH(
  req: Request,
  { params }: { params: { workspaceId: string; sessionId: string } },
) {
  const { workspaceId, sessionId } = params;
  const bad = validate(workspaceId, sessionId);
  if (bad) return bad;
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
    `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/chat-sessions/${encodeURIComponent(sessionId)}`,
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
