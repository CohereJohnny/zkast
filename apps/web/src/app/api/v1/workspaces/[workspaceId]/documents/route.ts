import { NextResponse } from "next/server";
import { z } from "zod";

import { getDb } from "@/lib/db";
import { pipelineFetch } from "@/lib/pipeline-client";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

function maxUploadBytes(): number {
  const raw = process.env.MAX_UPLOAD_BYTES ?? "52428800";
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : 52428800;
}

export async function GET(
  _req: Request,
  { params }: { params: { workspaceId: string } },
) {
  const { workspaceId } = params;
  if (!uuidParam.safeParse(workspaceId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid workspace id" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  try {
    const pool = getDb();
    const result = await pool.query<{
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
      WHERE workspace_id = $1::uuid
      ORDER BY created_at DESC
      LIMIT 200
      `,
      [workspaceId],
    );
    return NextResponse.json({ items: result.rows, next_cursor: null as string | null });
  } catch (err) {
    console.error("documents list failed", err);
    return NextResponse.json(
      { error: { code: "internal_error", message: "Database error" } },
      { status: 500 },
    );
  }
}

export async function POST(
  req: Request,
  { params }: { params: { workspaceId: string } },
) {
  const { workspaceId } = params;
  if (!uuidParam.safeParse(workspaceId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid workspace id" } },
      { status: 400 },
    );
  }
  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  const limit = maxUploadBytes();
  let formData: FormData;
  try {
    formData = await req.formData();
  } catch {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Expected multipart form data" } },
      { status: 400 },
    );
  }

  const files = formData.getAll("file").filter((v): v is File => v instanceof File);
  if (files.length === 0) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "No files uploaded (field name: file)" } },
      { status: 400 },
    );
  }

  const documents: Array<Record<string, unknown>> = [];
  const job_ids: string[] = [];

  for (const file of files) {
    if (file.size > limit) {
      return NextResponse.json(
        { error: { code: "payload_too_large", message: `File exceeds ${limit} bytes` } },
        { status: 413 },
      );
    }
    if (file.type && file.type !== "application/pdf") {
      return NextResponse.json(
        { error: { code: "unsupported_media_type", message: "Only application/pdf is accepted" } },
        { status: 415 },
      );
    }

    const upstream = new FormData();
    upstream.append("workspace_id", workspaceId);
    upstream.append("file", file);

    const replacesRaw = formData.get("replaces_document_id");
    if (typeof replacesRaw === "string" && uuidParam.safeParse(replacesRaw).success) {
      upstream.append("replaces_document_id", replacesRaw);
    }

    const idem = req.headers.get("idempotency-key");
    const headers: HeadersInit = {};
    if (idem) headers["Idempotency-Key"] = idem;

    let res: Response;
    try {
      res = await pipelineFetch("/internal/v1/documents", {
        method: "POST",
        body: upstream,
        headers,
        throwOnError: false,
      });
    } catch (err) {
      const base = process.env.PIPELINE_INTERNAL_URL ?? "http://localhost:8000";
      console.error("documents upload: pipeline unreachable", err);
      return NextResponse.json(
        {
          error: {
            code: "pipeline_unreachable",
            message: `Cannot reach the ingestion API (${base}). Start it with docker compose up -d pipeline worker. If you changed compose.yml ports, recreate: docker compose up -d pipeline --force-recreate.`,
          },
        },
        { status: 503 },
      );
    }

    const text = await res.text();
    if (!res.ok) {
      return new NextResponse(text, {
        status: res.status,
        headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
      });
    }

    try {
      const body = JSON.parse(text) as { document: Record<string, unknown>; job_id: string };
      documents.push({ ...body.document, job_id: body.job_id });
      job_ids.push(body.job_id);
    } catch {
      return NextResponse.json(
        { error: { code: "internal_error", message: "Invalid pipeline response" } },
        { status: 502 },
      );
    }
  }

  return NextResponse.json({ documents, job_ids }, { status: 202 });
}
