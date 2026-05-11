import { Pool } from "pg";

export type BypassUser = {
  id: string;
  displayName: string;
};

export type WorkspaceSummary = {
  id: string;
  name: string;
  slug: string;
};

const DEFAULT_WORKSPACE_ID = "00000000-0000-4000-8000-000000000002";

let pool: Pool | null = null;

function getPool(): Pool | null {
  const conn = process.env.DATABASE_URL;
  if (!conn) return null;
  if (!pool) {
    pool = new Pool({ connectionString: conn });
  }
  return pool;
}

/** P0 bypass user — server-only (FR-33). */
export async function getCurrentUser(): Promise<BypassUser> {
  const id =
    process.env.BYPASS_USER_ID ?? "00000000-0000-4000-8000-000000000001";
  return { id, displayName: "Local user" };
}

/**
 * Resolves the default workspace row when Postgres is reachable; otherwise
 * falls back to seeded IDs so `next build` and disconnected dev still work.
 */
export async function getCurrentWorkspace(): Promise<WorkspaceSummary> {
  const slug = process.env.DEFAULT_WORKSPACE_SLUG ?? "default";
  const db = getPool();

  if (!db) {
    return {
      id: DEFAULT_WORKSPACE_ID,
      name: "Default workspace",
      slug,
    };
  }

  try {
    const result = await db.query<{
      id: string;
      name: string;
      slug: string;
    }>(
      `SELECT id::text, name, slug FROM workspaces WHERE slug = $1 LIMIT 1`,
      [slug],
    );
    const row = result.rows[0];
    if (row) {
      return { id: row.id, name: row.name, slug: row.slug };
    }
  } catch (err) {
    console.error("getCurrentWorkspace query failed", err);
  }

  return {
    id: DEFAULT_WORKSPACE_ID,
    name: "Default workspace",
    slug,
  };
}
