import type { NextRequest } from "next/server";
import { z } from "zod";

import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

/**
 * SSE proxy for a chat turn.
 *
 * Internally the chat turn publishes every event (`retrieval_started`,
 * `retrieval_complete`, `token`, `citation`, `message_complete`,
 * `job_failed`, `job_cancelled`) to the same Redis pub/sub + Stream key
 * (`zkast:jobs:<turn_id>`) used by ingestion jobs — so we simply proxy
 * the existing internal jobs/events SSE endpoint. That keeps the wire
 * format identical to ingestion and lets the global JobLogConsole drawer
 * also subscribe to chat turns for free.
 */
export async function GET(
  req: NextRequest,
  { params }: { params: { workspaceId: string; turnId: string } },
) {
  const { workspaceId, turnId } = params;
  const queryWorkspaceId = req.nextUrl.searchParams.get("workspaceId") ?? workspaceId;
  if (
    !uuidParam.safeParse(workspaceId).success ||
    !uuidParam.safeParse(turnId).success ||
    !uuidParam.safeParse(queryWorkspaceId).success
  ) {
    return new Response(
      JSON.stringify({
        error: { code: "validation_failed", message: "Invalid id" },
      }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }
  const denied = await requireMatchingWorkspace(queryWorkspaceId);
  if (denied) return denied;

  const res = await pipelineFetch(
    `/internal/v1/jobs/${encodeURIComponent(turnId)}/events`,
    {
      workspaceId: queryWorkspaceId,
      throwOnError: false,
    },
  );

  if (!res.ok) {
    const body = await res.text();
    return new Response(body, {
      status: res.status,
      headers: {
        "Content-Type": res.headers.get("Content-Type") ?? "application/json",
      },
    });
  }

  return new Response(res.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
