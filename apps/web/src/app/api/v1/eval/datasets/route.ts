import { NextResponse } from "next/server";

import { pipelineFetch } from "@/lib/pipeline-client";

export const dynamic = "force-dynamic";

export async function GET() {
  const res = await pipelineFetch("/internal/v1/eval/datasets", {
    method: "GET",
    throwOnError: false,
  });
  const text = await res.text();
  return new NextResponse(text, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
