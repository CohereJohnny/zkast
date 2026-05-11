import { NextResponse } from "next/server";
import { z } from "zod";

import { getDb } from "@/lib/db";
import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

export async function GET(
  _req: Request,
  { params }: { params: { workspaceId: string; documentId: string } },
) {
  const { workspaceId, documentId } = params;
  if (!uuidParam.safeParse(workspaceId).success || !uuidParam.safeParse(documentId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid id" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  try {
    const pool = getDb();
    const doc = await pool.query<{
      id: string;
      original_filename: string;
      mime_type: string;
      byte_size: number;
      page_count: number | null;
      status: string;
      failure_reason: string | null;
      created_at: string;
      updated_at: string;
    }>(
      `
      SELECT id::text, original_filename, mime_type, byte_size, page_count,
             status, failure_reason, created_at, updated_at
      FROM documents
      WHERE id = $1::uuid AND workspace_id = $2::uuid
      LIMIT 1
      `,
      [documentId, workspaceId],
    );
    const row = doc.rows[0];
    if (!row) {
      return NextResponse.json(
        { error: { code: "not_found", message: "Document not found" } },
        { status: 404 },
      );
    }

    const runs = await pool.query<{
      id: string;
      started_at: string;
      ended_at: string | null;
      status: string;
      pipeline_version: string;
      stats: unknown;
    }>(
      `
      SELECT id::text, started_at, ended_at, status, pipeline_version, stats
      FROM ingestion_runs
      WHERE document_id = $1::uuid
      ORDER BY started_at DESC
      LIMIT 50
      `,
      [documentId],
    );

    return NextResponse.json({ document: row, ingestion_runs: runs.rows });
  } catch (err) {
    console.error("document get failed", err);
    return NextResponse.json(
      { error: { code: "internal_error", message: "Database error" } },
      { status: 500 },
    );
  }
}

export async function DELETE(
  _req: Request,
  { params }: { params: { workspaceId: string; documentId: string } },
) {
  const { workspaceId, documentId } = params;
  if (!uuidParam.safeParse(workspaceId).success || !uuidParam.safeParse(documentId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid id" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  const res = await pipelineFetch(
    `/internal/v1/documents/${documentId}?workspace_id=${encodeURIComponent(workspaceId)}`,
    { method: "DELETE", throwOnError: false },
  );

  if (res.status === 204) {
    return new NextResponse(null, { status: 204 });
  }

  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
