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

const sourceKindSchema = z.enum(["pdf", "north_conversation", "all"]);

export async function GET(
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

  const url = new URL(req.url);
  const rawKind = url.searchParams.get("source_kind");
  const sourceKindParsed = rawKind ? sourceKindSchema.safeParse(rawKind) : null;
  if (rawKind && !sourceKindParsed?.success) {
    return NextResponse.json(
      {
        error: {
          code: "validation_failed",
          message: "source_kind must be pdf, north_conversation, or all",
        },
      },
      { status: 400 },
    );
  }
  const sourceKind = sourceKindParsed?.success ? sourceKindParsed.data : "pdf";

  try {
    const pool = getDb();
    if (sourceKind === "all") {
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
        source_kind: string;
        conversation_title: string | null;
        agent_display_name: string | null;
      }>(
        `
        WITH combined AS (
          SELECT d.id::text AS id,
                 d.original_filename AS original_filename,
                 d.mime_type AS mime_type,
                 d.byte_size AS byte_size,
                 d.page_count AS page_count,
                 d.status AS status,
                 d.failure_reason AS failure_reason,
                 d.created_at AS created_at,
                 d.updated_at AS updated_at,
                 'pdf'::text AS source_kind,
                 NULL::text AS conversation_title,
                 NULL::text AS agent_display_name
          FROM documents d
          WHERE d.workspace_id = $1::uuid AND d.source_kind = 'pdf'
          UNION ALL
          SELECT d.id::text,
                 d.original_filename AS original_filename,
                 d.mime_type AS mime_type,
                 d.byte_size AS byte_size,
                 d.page_count AS page_count,
                 d.status AS status,
                 d.failure_reason AS failure_reason,
                 d.created_at AS created_at,
                 d.updated_at AS updated_at,
                 'north_conversation'::text AS source_kind,
                 COALESCE(
                   NULLIF(TRIM(COALESCE(d.north_metadata->>'conversation_title', '')), ''),
                   NULLIF(TRIM(COALESCE(d.original_filename, '')), ''),
                   d.id::text
                 ) AS conversation_title,
                 NULLIF(TRIM(COALESCE(
                   NULLIF(TRIM(COALESCE(na.display_name, '')), ''),
                   NULLIF(TRIM(COALESCE(d.north_metadata->>'agent_display_name', '')), ''),
                   ''
                 )), '') AS agent_display_name
          FROM documents d
          LEFT JOIN north_agents na
            ON na.id = d.agent_id AND na.workspace_id = d.workspace_id
          WHERE d.workspace_id = $1::uuid AND d.source_kind = 'north_conversation'
        )
        SELECT * FROM combined
        ORDER BY created_at DESC
        LIMIT 250
        `,
        [workspaceId],
      );
      return NextResponse.json({ items: result.rows, next_cursor: null as string | null });
    }

    if (sourceKind === "north_conversation") {
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
        agent_id: string | null;
        agent_display_name: string;
        conversation_title: string;
        north_conversation_id: string | null;
        conversation_activity_at: string | null;
      }>(
        `
        SELECT d.id::text,
               d.original_filename,
               d.mime_type,
               d.byte_size,
               d.page_count,
               d.status,
               d.failure_reason,
               d.created_at,
               d.updated_at,
               d.agent_id::text AS agent_id,
               COALESCE(
                 NULLIF(TRIM(COALESCE(na.display_name, '')), ''),
                 NULLIF(TRIM(COALESCE(d.north_metadata->>'agent_display_name', '')), ''),
                 'Unknown agent'
               ) AS agent_display_name,
               COALESCE(
                 NULLIF(TRIM(COALESCE(d.north_metadata->>'conversation_title', '')), ''),
                 NULLIF(TRIM(COALESCE(d.original_filename, '')), ''),
                 d.id::text
               ) AS conversation_title,
               d.north_conversation_id,
               NULLIF(TRIM(COALESCE(d.north_metadata->>'conversation_activity_at', '')), '')
                 AS conversation_activity_at
        FROM documents d
        LEFT JOIN north_agents na
          ON na.id = d.agent_id AND na.workspace_id = d.workspace_id
        WHERE d.workspace_id = $1::uuid AND d.source_kind = 'north_conversation'
        ORDER BY agent_display_name ASC, d.created_at DESC
        LIMIT 200
        `,
        [workspaceId],
      );
      return NextResponse.json({ items: result.rows, next_cursor: null as string | null });
    }

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
      WHERE workspace_id = $1::uuid AND source_kind = $2::text
      ORDER BY created_at DESC
      LIMIT 200
      `,
      [workspaceId, sourceKind],
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
