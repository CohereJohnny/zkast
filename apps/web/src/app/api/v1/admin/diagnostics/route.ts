import { NextResponse } from "next/server";

import { pipelineFetch } from "@/lib/pipeline-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  // Self-host single-user mode: gate on the bypass workspace.
  const ws = await getCurrentWorkspace();
  const url = new URL(req.url);
  const qs = new URLSearchParams(url.searchParams);
  if (!qs.has("workspace_id")) qs.set("workspace_id", ws.id);
  const path = `/internal/v1/admin/diagnostics?${qs.toString()}`;
  const res = await pipelineFetch(path, { method: "GET", throwOnError: false });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
