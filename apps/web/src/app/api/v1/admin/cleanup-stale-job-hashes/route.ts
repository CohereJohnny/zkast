import { NextResponse } from "next/server";

import { pipelineFetch } from "@/lib/pipeline-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function POST() {
  await getCurrentWorkspace();
  const res = await pipelineFetch(
    `/internal/v1/admin/cleanup-stale-job-hashes`,
    { method: "POST", throwOnError: false },
  );
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
