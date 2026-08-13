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
      source_kind: string;
      collection_id: string | null;
      collection_name: string | null;
    }>(
      `
      SELECT d.id::text, d.original_filename, d.mime_type, d.byte_size, d.page_count,
             d.status, d.failure_reason, d.created_at, d.updated_at, d.source_kind,
             d.collection_id::text AS collection_id,
             dc.name AS collection_name
      FROM documents d
      LEFT JOIN document_collections dc ON dc.id = d.collection_id
      WHERE d.id = $1::uuid AND d.workspace_id = $2::uuid
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
      ontology_name: string;
      ontology_version: string;
      stats: unknown;
    }>(
      `
      SELECT id::text, started_at, ended_at, status, pipeline_version,
             ontology_name, ontology_version, stats
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
  req: Request,
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

  const url = new URL(req.url);
  const cascade = url.searchParams.get("cascade") ?? "document_only";
  if (cascade !== "document_only" && cascade !== "exclusive_derivatives") {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid cascade parameter" } },
      { status: 400 },
    );
  }
  const force = url.searchParams.get("force") === "true";

  const qs = new URLSearchParams({
    workspace_id: workspaceId,
    cascade,
  });
  if (force) qs.set("force", "true");

  const res = await pipelineFetch(
    `/internal/v1/documents/${documentId}?${qs.toString()}`,
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
