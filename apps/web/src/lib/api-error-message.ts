/**
 * Extract a human-readable error message from JSON API bodies.
 *
 * FastAPI ``HTTPException(detail={...})`` serializes as ``{ "detail": ... }``.
 * zkast web routes often use ``{ "error": { "message": "..." } }``.
 */
export function readApiErrorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object" || body === null) {
    return fallback;
  }
  const o = body as Record<string, unknown>;

  const err = o.error;
  if (err && typeof err === "object" && err !== null) {
    const em = (err as Record<string, unknown>).message;
    if (typeof em === "string" && em.trim()) {
      return em.trim();
    }
  }

  const detail = o.detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail.trim();
  }
  if (detail && typeof detail === "object") {
    const d = detail as Record<string, unknown>;
    const inner = d.error;
    if (inner && typeof inner === "object" && inner !== null) {
      const m = (inner as Record<string, unknown>).message;
      if (typeof m === "string" && m.trim()) {
        return m.trim();
      }
    }
    const dm = d.message;
    if (typeof dm === "string" && dm.trim()) {
      return dm.trim();
    }
  }

  return fallback;
}
