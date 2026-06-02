import { randomUUID } from "crypto";
import { NextResponse } from "next/server";
import { z } from "zod";

import { encryptSecret } from "@/lib/crypto";
import { getDb } from "@/lib/db";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

const postSchema = z.discriminatedUnion("kind", [
  z.object({
    kind: z.literal("llm_cohere"),
    label: z.string().min(1).max(80),
    secret: z.string().min(8),
    metadata: z.record(z.string(), z.unknown()).optional(),
  }),
  z.object({
    kind: z.literal("north_bearer"),
    label: z.string().min(1).max(80),
    secret: z.string().min(8),
    metadata: z.record(z.string(), z.unknown()).optional(),
  }),
  z.object({
    kind: z.literal("llm_openai"),
    label: z.string().min(1).max(80),
    secret: z.string().min(8),
    metadata: z.record(z.string(), z.unknown()).optional(),
  }),
  z.object({
    kind: z.literal("llm_azure_openai"),
    label: z.string().min(1).max(80),
    secret: z.string().min(8),
    metadata: z.record(z.string(), z.unknown()).optional(),
  }),
]);

export async function GET(
  _req: Request,
  { params }: { params: { workspaceId: string } },
) {
  const { workspaceId } = params;
  const idParse = uuidParam.safeParse(workspaceId);
  if (!idParse.success) {
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
      kind: string;
      label: string;
      metadata: unknown;
      created_at: string;
      updated_at: string;
      last_used_at: string | null;
    }>(
      `
      SELECT id::text, kind, label, metadata, created_at, updated_at, last_used_at
      FROM api_keys
      WHERE workspace_id = $1::uuid
      ORDER BY created_at DESC
      `,
      [workspaceId],
    );

    return NextResponse.json({
      items: result.rows,
      next_cursor: null as string | null,
    });
  } catch (err) {
    console.error("api-keys list failed", err);
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
  const idParse = uuidParam.safeParse(workspaceId);
  if (!idParse.success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid workspace id" } },
      { status: 400 },
    );
  }

  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  const masterKey = process.env.MASTER_ENCRYPTION_KEY;
  if (!masterKey) {
    return NextResponse.json(
      { error: { code: "internal_error", message: "MASTER_ENCRYPTION_KEY is not configured" } },
      { status: 500 },
    );
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid JSON body" } },
      { status: 400 },
    );
  }

  const parsed = postSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      {
        error: {
          code: "validation_failed",
          message: "Invalid body",
          details: parsed.error.flatten(),
        },
      },
      { status: 400 },
    );
  }

  const enc = encryptSecret(masterKey, parsed.data.secret);
  const meta = parsed.data.metadata ?? {};
  const id = randomUUID();

  try {
    const pool = getDb();
    const inserted = await pool.query<{
      id: string;
      kind: string;
      label: string;
      metadata: unknown;
      created_at: string;
      updated_at: string;
      last_used_at: string | null;
    }>(
      `
      INSERT INTO api_keys (id, workspace_id, kind, label, encrypted_secret, metadata)
      VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::jsonb)
      RETURNING id::text, kind, label, metadata, created_at, updated_at, last_used_at
      `,
      [id, workspaceId, parsed.data.kind, parsed.data.label, enc, JSON.stringify(meta)],
    );

    const row = inserted.rows[0];
    if (!row) {
      throw new Error("insert returned no row");
    }

    return NextResponse.json(row, { status: 201 });
  } catch (err: unknown) {
    const pg = err as { code?: string };
    if (pg.code === "23505") {
      const msg =
        parsed.data.kind === "north_bearer"
          ? "A North bearer token already exists for this workspace. Remove it or rotate via PATCH."
          : "A Cohere API key already exists for this workspace. Remove it or rotate via PATCH.";
      return NextResponse.json(
        {
          error: {
            code: "conflict",
            message: msg,
          },
        },
        { status: 409 },
      );
    }
    console.error("api-keys create failed", err);
    return NextResponse.json(
      { error: { code: "internal_error", message: "Database error" } },
      { status: 500 },
    );
  }
}
