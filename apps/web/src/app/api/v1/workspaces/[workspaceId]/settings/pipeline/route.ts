import { NextResponse } from "next/server";
import { z } from "zod";

import { getDb } from "@/lib/db";
import {
  mergePipelineSettings,
  pipelineSettingsPatchSchema,
  pipelineSettingsSchema,
} from "@/lib/pipeline-settings";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

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
    const result = await pool.query<{ pipeline_settings: unknown }>(
      `SELECT pipeline_settings FROM workspaces WHERE id = $1::uuid`,
      [workspaceId],
    );
    const row = result.rows[0];
    if (!row) {
      return NextResponse.json({ error: { code: "not_found", message: "Workspace not found" } }, { status: 404 });
    }

    const settings = mergePipelineSettings(row.pipeline_settings);
    return NextResponse.json(settings);
  } catch (err) {
    console.error("pipeline settings get failed", err);
    return NextResponse.json(
      { error: { code: "internal_error", message: "Database error" } },
      { status: 500 },
    );
  }
}

export async function PATCH(
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

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid JSON body" } },
      { status: 400 },
    );
  }

  const parsed = pipelineSettingsPatchSchema.safeParse(body);
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

  try {
    const pool = getDb();
    const result = await pool.query<{ pipeline_settings: unknown }>(
      `SELECT pipeline_settings FROM workspaces WHERE id = $1::uuid`,
      [workspaceId],
    );
    const row = result.rows[0];
    if (!row) {
      return NextResponse.json({ error: { code: "not_found", message: "Workspace not found" } }, { status: 404 });
    }

    const current = mergePipelineSettings(row.pipeline_settings);
    const mergedRaw = { ...current, ...parsed.data };
    const next = pipelineSettingsSchema.parse(mergedRaw);

    await pool.query(
      `UPDATE workspaces SET pipeline_settings = $1::jsonb, updated_at = now() WHERE id = $2::uuid`,
      [JSON.stringify(next), workspaceId],
    );

    return NextResponse.json(next);
  } catch (err) {
    console.error("pipeline settings patch failed", err);
    return NextResponse.json(
      { error: { code: "internal_error", message: "Database error" } },
      { status: 500 },
    );
  }
}
