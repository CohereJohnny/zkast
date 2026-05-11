import { Pool } from "pg";

let pool: Pool | null = null;

export function getDb(): Pool {
  const conn = process.env.DATABASE_URL;
  if (!conn) {
    throw new Error("DATABASE_URL is not configured");
  }
  if (!pool) {
    pool = new Pool({ connectionString: conn });
  }
  return pool;
}
