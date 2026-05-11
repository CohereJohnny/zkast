import { NextResponse } from "next/server";

import { pipelineFetch } from "@/lib/pipeline-client";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const res = await pipelineFetch("/readyz", { throwOnError: false });
    const pipelineBody: unknown = await res.json().catch(() => ({}));
    const bodyObj =
      pipelineBody && typeof pipelineBody === "object"
        ? (pipelineBody as Record<string, unknown>)
        : {};
    const pipelineOk = res.ok && bodyObj.status === "ok";
    const status = pipelineOk ? "ok" : "degraded";

    return NextResponse.json(
      {
        status,
        web: { status: "ok" },
        pipeline: pipelineBody,
      },
      { status: pipelineOk ? 200 : 503 },
    );
  } catch (err) {
    console.error("readyz aggregation failed", err);
    return NextResponse.json(
      {
        status: "error",
        web: { status: "ok" },
        pipeline: {
          status: "error",
          detail: err instanceof Error ? err.message : String(err),
        },
      },
      { status: 503 },
    );
  }
}
