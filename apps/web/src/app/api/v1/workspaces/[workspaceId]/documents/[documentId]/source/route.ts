import { NextResponse } from "next/server";
import { z } from "zod";

import { getDb } from "@/lib/db";
import { requireMatchingWorkspace } from "@/lib/workspace-access";

export const dynamic = "force-dynamic";

const uuidParam = z.string().uuid();

export async function GET(
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
  const episodeId = url.searchParams.get("episode");
  const highlightRaw = url.searchParams.get("highlight");
  const highlight =
    highlightRaw != null && highlightRaw.trim() !== "" ? Number(highlightRaw) : null;

  if (episodeId && !uuidParam.safeParse(episodeId).success) {
    return NextResponse.json(
      { error: { code: "validation_failed", message: "Invalid episode id" } },
      { status: 400 },
    );
  }

  try {
    const pool = getDb();
    const docRes = await pool.query<{
      id: string;
      original_filename: string;
      source_kind: string;
      mime_type: string;
      status: string;
      agent_id: string | null;
    }>(
      `
      SELECT id::text,
             original_filename,
             source_kind,
             mime_type,
             status,
             agent_id::text AS agent_id
      FROM documents
      WHERE id = $1::uuid AND workspace_id = $2::uuid
      LIMIT 1
      `,
      [documentId, workspaceId],
    );
    const doc = docRes.rows[0];
    if (!doc) {
      return NextResponse.json(
        { error: { code: "not_found", message: "Document not found" } },
        { status: 404 },
      );
    }

    type EpRow = {
      id: string;
      text: string;
      page_start: number | null;
      page_end: number | null;
      kind: string;
      sequence: number;
    };

    let episode: EpRow | undefined;

    if (episodeId) {
      const epRes = await pool.query<EpRow>(
        `
        SELECT id::text, text, page_start, page_end, kind, sequence
        FROM episodes
        WHERE id = $1::uuid AND document_id = $2::uuid AND workspace_id = $3::uuid
        LIMIT 1
        `,
        [episodeId, documentId, workspaceId],
      );
      episode = epRes.rows[0];
    } else if (highlight != null && Number.isFinite(highlight)) {
      const epRes = await pool.query<EpRow>(
        `
        SELECT id::text, text, page_start, page_end, kind, sequence
        FROM episodes
        WHERE document_id = $1::uuid AND workspace_id = $2::uuid
          AND char_length(text) > $3::int
        ORDER BY sequence ASC
        LIMIT 1
        `,
        [documentId, workspaceId, Math.max(0, Math.floor(highlight))],
      );
      episode = epRes.rows[0];
    }

    if (!episode) {
      const epRes = await pool.query<EpRow>(
        `
        SELECT id::text, text, page_start, page_end, kind, sequence
        FROM episodes
        WHERE document_id = $1::uuid AND workspace_id = $2::uuid
        ORDER BY sequence ASC
        LIMIT 1
        `,
        [documentId, workspaceId],
      );
      episode = epRes.rows[0];
    }

    if (!episode) {
      return NextResponse.json(
        { error: { code: "not_found", message: "No source episodes for this document" } },
        { status: 404 },
      );
    }

    return NextResponse.json({
      document: doc,
      episode: {
        id: episode.id,
        text: episode.text,
        page_start: episode.page_start,
        page_end: episode.page_end,
        kind: episode.kind,
        sequence: episode.sequence,
      },
    });
  } catch (err) {
    console.error("document source get failed", err);
    return NextResponse.json(
      { error: { code: "internal_error", message: "Database error" } },
      { status: 500 },
    );
  }
}
