import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

export async function GET(
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

  const url = new URL(req.url);
  const qs = url.searchParams.toString();
  const path = `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/graph/entities/${encodeURIComponent(entityId)}${qs ? `?${qs}` : ""}`;

  const res = await pipelineFetch(path, { method: "GET", throwOnError: false });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}

const patchBody = z.object({
  canonical_name: z.string().min(1).max(500).optional(),
  type: z.string().min(1).max(120).optional(),
  aliases: z.array(z.string()).optional(),
  summary: z.string().max(2000).optional(),
  properties: z.record(z.string(), z.unknown()).optional(),
});

export async function PATCH(
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
  const parsed = patchBody.safeParse(json);
  if (!parsed.success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: parsed.error.message } },
      { status: 400 },
    );
  }

  const res = await pipelineFetch(
    `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/graph/entities/${encodeURIComponent(entityId)}`,
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

  const res = await pipelineFetch(
    `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/graph/entities/${encodeURIComponent(entityId)}`,
    { method: "DELETE", throwOnError: false },
  );
  if (res.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
