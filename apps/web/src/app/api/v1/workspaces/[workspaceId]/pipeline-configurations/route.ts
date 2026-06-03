import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

async function proxy(workspaceId: string, init: RequestInit & { throwOnError: false }) {
  const res = await pipelineFetch(
    `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/pipeline-configurations`,
    init,
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}

export async function GET(
  _req: Request,
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
  return proxy(workspaceId, { method: "GET", throwOnError: false });
}

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
  const body = await req.text();
  return proxy(workspaceId, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    throwOnError: false,
  });
}
