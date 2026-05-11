import { NextResponse } from "next/server";

import { pipelineFetch } from "@/lib/pipeline-client";

const WEB_VERSION = "0.0.1";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const res = await pipelineFetch("/version", { throwOnError: false });
    const body: unknown = await res.json().catch(() => ({}));
    const obj =
      body && typeof body === "object"
        ? (body as Record<string, unknown>)
        : {};

    return NextResponse.json({
      web: WEB_VERSION,
      pipeline: typeof obj.pipeline === "string" ? obj.pipeline : null,
      contract: typeof obj.contract === "string" ? obj.contract : "v1",
    });
  } catch (err) {
    console.error("version fetch failed", err);
    return NextResponse.json({
      web: WEB_VERSION,
      pipeline: null,
      contract: "v1",
    });
  }
}
