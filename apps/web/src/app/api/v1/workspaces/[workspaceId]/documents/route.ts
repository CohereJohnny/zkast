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

const sourceKindSchema = z.enum([
  "pdf",
  "text",
  "markdown",
  "email",
  "north_conversation",
  "slack_conversation",
  "all",
  "uploads",
]);

const ACCEPTED_UPLOAD_EXT = new Set(["pdf", "txt", "md", "markdown", "eml"]);
const ACCEPTED_UPLOAD_MIME = new Set([
  "application/pdf",
  "text/plain",
  "text/markdown",
  "text/x-markdown",
  "message/rfc822",
  "application/eml",
  "",
]);

function uploadExtOk(name: string): boolean {
  const lower = name.toLowerCase();
  const ext = lower.includes(".") ? lower.split(".").pop() ?? "" : "";
  return ACCEPTED_UPLOAD_EXT.has(ext);
}

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
          message:
            "source_kind must be pdf, text, markdown, email, uploads, north_conversation, slack_conversation, or all",
        },
      },
      { status: 400 },
    );
  }
  const sourceKind = sourceKindParsed?.success ? sourceKindParsed.data : "pdf";
  const agentIdRaw = url.searchParams.get("agent_id");
  const agentIdParsed = agentIdRaw ? uuidParam.safeParse(agentIdRaw) : null;
  if (agentIdRaw && !agentIdParsed?.success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "agent_id must be a UUID" } },
      { status: 400 },
    );
  }
  const agentId = agentIdParsed?.success ? agentIdParsed.data : null;
  if (agentId && sourceKind !== "slack_conversation") {
    return NextResponse.json(
      {
        error: {
          code: "validation_failed",
          message: "agent_id filter is only supported with source_kind=slack_conversation",
        },
      },
      { status: 400 },
    );
  }
  const collectionIdRaw = url.searchParams.get("collection_id");
  const collectionIdParsed = collectionIdRaw ? uuidParam.safeParse(collectionIdRaw) : null;
  if (collectionIdRaw && !collectionIdParsed?.success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "collection_id must be a UUID" } },
      { status: 400 },
    );
  }
  const collectionId = collectionIdParsed?.success ? collectionIdParsed.data : null;

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
        collection_id: string | null;
        collection_name: string | null;
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
                 d.source_kind::text AS source_kind,
                 NULL::text AS conversation_title,
                 NULL::text AS agent_display_name,
                 d.collection_id::text AS collection_id,
                 dc.name AS collection_name
          FROM documents d
          LEFT JOIN document_collections dc ON dc.id = d.collection_id
          WHERE d.workspace_id = $1::uuid
            AND d.source_kind IN ('pdf', 'text', 'markdown', 'email')
            AND ($2::uuid IS NULL OR d.collection_id = $2::uuid)
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
                 )), '') AS agent_display_name,
                 NULL::text AS collection_id,
                 NULL::text AS collection_name
          FROM documents d
          LEFT JOIN north_agents na
            ON na.id = d.agent_id AND na.workspace_id = d.workspace_id
          WHERE d.workspace_id = $1::uuid AND d.source_kind = 'north_conversation'
            AND $2::uuid IS NULL
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
                 'slack_conversation'::text AS source_kind,
                 COALESCE(
                   NULLIF(TRIM(COALESCE(d.source_metadata->>'title', '')), ''),
                   NULLIF(TRIM(COALESCE(d.original_filename, '')), ''),
                   d.id::text
                 ) AS conversation_title,
                 NULLIF(TRIM(COALESCE(
                   NULLIF(TRIM(COALESCE(na.display_name, '')), ''),
                   NULLIF(TRIM(COALESCE(d.source_metadata->>'channel_name', '')), ''),
                   ''
                 )), '') AS agent_display_name,
                 NULL::text AS collection_id,
                 NULL::text AS collection_name
          FROM documents d
          LEFT JOIN north_agents na
            ON na.id = d.agent_id AND na.workspace_id = d.workspace_id
          WHERE d.workspace_id = $1::uuid AND d.source_kind = 'slack_conversation'
            AND $2::uuid IS NULL
        )
        SELECT * FROM combined
        ORDER BY created_at DESC
        LIMIT 400
        `,
        [workspaceId, collectionId],
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
        memory_notes: number;
        memory_amem_embeddings: number;
        memory_ingest_digest: string | null;
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
                 AS conversation_activity_at,
               coalesce(note_agg.note_count, 0) AS memory_notes,
               coalesce(amem_agg.amem_count, 0) AS memory_amem_embeddings,
               CASE
                 WHEN length(coalesce(d.north_metadata->>'ingest_content_hash', '')) >= 12
                 THEN left(d.north_metadata->>'ingest_content_hash', 12)
                 ELSE NULL
               END AS memory_ingest_digest
        FROM documents d
        LEFT JOIN north_agents na
          ON na.id = d.agent_id AND na.workspace_id = d.workspace_id
        LEFT JOIN LATERAL (
          SELECT count(DISTINCT n.id)::int AS note_count
          FROM episodes e
          INNER JOIN note_episodes ne ON ne.episode_id = e.id
          INNER JOIN atomic_notes n ON n.id = ne.note_id
          WHERE e.document_id = d.id
        ) note_agg ON true
        LEFT JOIN LATERAL (
          SELECT count(DISTINCT re.id)::int AS amem_count
          FROM episodes e
          INNER JOIN note_episodes ne ON ne.episode_id = e.id
          INNER JOIN atomic_notes n ON n.id = ne.note_id
          INNER JOIN retrieval_embeddings re
            ON re.workspace_id = d.workspace_id
           AND re.index_kind = 'note_amem'
           AND re.source_kind = 'atomic_note'
           AND re.source_id = n.id::text
          WHERE e.document_id = d.id
        ) amem_agg ON true
        WHERE d.workspace_id = $1::uuid AND d.source_kind = 'north_conversation'
        ORDER BY agent_display_name ASC, d.created_at DESC
        LIMIT 200
        `,
        [workspaceId],
      );
      const items = result.rows.map((row) => {
        const {
          memory_notes,
          memory_amem_embeddings,
          memory_ingest_digest,
          ...rest
        } = row;
        return {
          ...rest,
          memory: {
            notes: memory_notes,
            amem_embeddings: memory_amem_embeddings,
            document_status: rest.status,
            ingest_digest: memory_ingest_digest,
          },
        };
      });
      return NextResponse.json({ items, next_cursor: null as string | null });
    }

    if (sourceKind === "slack_conversation") {
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
        conversation_title: string | null;
        agent_display_name: string | null;
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
               COALESCE(
                 NULLIF(TRIM(COALESCE(d.source_metadata->>'title', '')), ''),
                 NULLIF(TRIM(COALESCE(d.original_filename, '')), ''),
                 d.id::text
               ) AS conversation_title,
               NULLIF(TRIM(COALESCE(
                 NULLIF(TRIM(COALESCE(na.display_name, '')), ''),
                 NULLIF(TRIM(COALESCE(d.source_metadata->>'channel_name', '')), ''),
                 ''
               )), '') AS agent_display_name
        FROM documents d
        LEFT JOIN north_agents na
          ON na.id = d.agent_id AND na.workspace_id = d.workspace_id
        WHERE d.workspace_id = $1::uuid
          AND d.source_kind = 'slack_conversation'
          AND ($2::uuid IS NULL OR d.agent_id = $2::uuid)
        ORDER BY d.created_at DESC
        LIMIT 200
        `,
        [workspaceId, agentId],
      );
      return NextResponse.json({ items: result.rows, next_cursor: null as string | null });
    }

    const uploadKinds =
      sourceKind === "uploads"
        ? (["pdf", "text", "markdown", "email"] as const)
        : ([sourceKind] as const);
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
      WHERE d.workspace_id = $1::uuid
        AND d.source_kind = ANY($2::text[])
        AND ($3::uuid IS NULL OR d.collection_id = $3::uuid)
      ORDER BY d.created_at DESC
      LIMIT 200
      `,
      [workspaceId, [...uploadKinds], collectionId],
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

  const collectionNameRaw = formData.get("collection_name");
  const collectionName =
    typeof collectionNameRaw === "string" && collectionNameRaw.trim()
      ? collectionNameRaw.trim()
      : null;
  const collectionIdRaw = formData.get("collection_id");
  const collectionId =
    typeof collectionIdRaw === "string" && uuidParam.safeParse(collectionIdRaw).success
      ? collectionIdRaw
      : null;

  for (const file of files) {
    if (file.size > limit) {
      return NextResponse.json(
        { error: { code: "payload_too_large", message: `File exceeds ${limit} bytes` } },
        { status: 413 },
      );
    }
    const mimeOk = ACCEPTED_UPLOAD_MIME.has(file.type);
    if (!mimeOk && !uploadExtOk(file.name)) {
      return NextResponse.json(
        {
          error: {
            code: "unsupported_media_type",
            message: "Accepted types: PDF, TXT, MD, EML",
          },
        },
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

    const ontologyName = formData.get("ontology_name");
    if (typeof ontologyName === "string" && ontologyName.trim()) {
      upstream.append("ontology_name", ontologyName.trim());
    }
    const ontologyVersion = formData.get("ontology_version");
    if (typeof ontologyVersion === "string" && ontologyVersion.trim()) {
      upstream.append("ontology_version", ontologyVersion.trim());
    }
    if (collectionId) {
      upstream.append("collection_id", collectionId);
    } else if (collectionName) {
      upstream.append("collection_name", collectionName);
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
