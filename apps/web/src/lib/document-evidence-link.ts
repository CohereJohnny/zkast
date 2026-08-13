/** Deep link to the document source viewer with optional highlight offsets. */
export function documentEvidenceHref(
  documentId: string,
  opts?: {
    charStart?: number;
    charEnd?: number;
    page?: number;
    episodeId?: string | null;
  },
): string {
  const qs = new URLSearchParams();
  if (opts?.page != null && opts.page > 0) qs.set("page", String(opts.page));
  if (opts?.charStart != null && Number.isFinite(opts.charStart)) {
    qs.set("highlight", String(Math.max(0, Math.floor(opts.charStart))));
  }
  if (opts?.charEnd != null && Number.isFinite(opts.charEnd)) {
    qs.set("end", String(Math.max(0, Math.floor(opts.charEnd))));
  }
  if (opts?.episodeId) qs.set("episode", opts.episodeId);
  const q = qs.toString();
  return `/documents/${encodeURIComponent(documentId)}${q ? `?${q}` : ""}`;
}
