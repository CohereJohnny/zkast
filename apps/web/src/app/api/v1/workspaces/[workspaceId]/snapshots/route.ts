import { NextResponse } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

export async function GET(req: Request, { params }: { params: { workspaceId: string } }) {
  const { workspaceId } = params;
  if (!uuidParam.safeParse(workspaceId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid workspace id" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  const url = new URL(req.url);
  const qs = url.searchParams.toString();
  const path = `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/snapshots${qs ? `?${qs}` : ""}`;

  const res = await pipelineFetch(path, { method: "GET", throwOnError: false });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}

const createBody = z.object({
  name: z.string().min(1).max(120),
  description: z.string().max(1000).optional().nullable(),
});

export async function POST(req: Request, { params }: { params: { workspaceId: string } }) {
  const { workspaceId } = params;
  if (!uuidParam.safeParse(workspaceId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid workspace id" } },
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
  const parsed = createBody.safeParse(json);
  if (!parsed.success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: parsed.error.message } },
      { status: 400 },
    );
  }

  const res = await pipelineFetch(
    `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/snapshots`,
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
