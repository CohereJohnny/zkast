import { NextResponse } from "next/server";
import { z } from "zod";

import { encryptSecret } from "@/lib/crypto";
import { getDb } from "@/lib/db";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

const patchSchema = z.object({
  label: z.string().min(1).max(80).optional(),
  secret: z.string().min(8).optional(),
  metadata: z.record(z.string(), z.unknown()).optional(),
});

export async function PATCH(
  req: Request,
  {
    params,
  }: { params: { workspaceId: string; apiKeyId: string } },
) {
  const { workspaceId, apiKeyId } = params;

  if (!uuidParam.safeParse(workspaceId).success || !uuidParam.safeParse(apiKeyId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid id" } },
      { status: 400 },
    );
  }

  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid JSON body" } },
      { status: 400 },
    );
  }

  const parsed = patchSchema.safeParse(body);
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

  const masterKey = process.env.MASTER_ENCRYPTION_KEY;
  if (!masterKey) {
    return NextResponse.json(
      { error: { code: "internal_error", message: "MASTER_ENCRYPTION_KEY is not configured" } },
      { status: 500 },
    );
  }

  const pool = getDb();

  const existing = await pool.query<{ kind: string }>(
    `SELECT kind FROM api_keys WHERE id = $1::uuid AND workspace_id = $2::uuid`,
    [apiKeyId, workspaceId],
  );
  const row = existing.rows[0];
  if (!row) {
    return NextResponse.json({ error: { code: "not_found", message: "API key not found" } }, { status: 404 });
  }

  let enc: string | undefined;
  if (parsed.data.secret) {
    enc = encryptSecret(masterKey, parsed.data.secret);
  }

  const metaJson =
    parsed.data.metadata !== undefined ? JSON.stringify(parsed.data.metadata) : undefined;

  try {
    const updated = await pool.query<{
      id: string;
      kind: string;
      label: string;
      metadata: unknown;
      created_at: string;
      updated_at: string;
      last_used_at: string | null;
    }>(
      `
      UPDATE api_keys SET
        label = COALESCE($3, label),
        encrypted_secret = COALESCE($4, encrypted_secret),
        metadata = COALESCE($5::jsonb, metadata),
        updated_at = now()
      WHERE id = $1::uuid AND workspace_id = $2::uuid
      RETURNING id::text, kind, label, metadata, created_at, updated_at, last_used_at
      `,
      [apiKeyId, workspaceId, parsed.data.label ?? null, enc ?? null, metaJson ?? null],
    );

    const out = updated.rows[0];
    if (!out) {
      return NextResponse.json({ error: { code: "not_found", message: "API key not found" } }, { status: 404 });
    }

    return NextResponse.json(out);
  } catch (err) {
    console.error("api-keys patch failed", err);
    return NextResponse.json(
      { error: { code: "internal_error", message: "Database error" } },
      { status: 500 },
    );
  }
}

export async function DELETE(
  _req: Request,
  {
    params,
  }: { params: { workspaceId: string; apiKeyId: string } },
) {
  const { workspaceId, apiKeyId } = params;

  if (!uuidParam.safeParse(workspaceId).success || !uuidParam.safeParse(apiKeyId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid id" } },
      { status: 400 },
    );
  }

  const denied = await requireMatchingWorkspace(workspaceId);
  if (denied) return denied;

  try {
    const pool = getDb();
    const del = await pool.query(
      `DELETE FROM api_keys WHERE id = $1::uuid AND workspace_id = $2::uuid RETURNING id`,
      [apiKeyId, workspaceId],
    );
    if (del.rowCount === 0) {
      return NextResponse.json({ error: { code: "not_found", message: "API key not found" } }, { status: 404 });
    }
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    console.error("api-keys delete failed", err);
    return NextResponse.json(
      { error: { code: "internal_error", message: "Database error" } },
      { status: 500 },
    );
  }
}
