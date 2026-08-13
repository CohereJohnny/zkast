"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { documentEvidenceHref } from "@/lib/document-evidence-link";

type SourcePayload = {
  document: {
    id: string;
    original_filename: string;
    source_kind: string;
    mime_type: string;
    status: string;
    agent_id: string | null;
  };
  episode: {
    id: string;
    text: string;
    page_start: number | null;
    page_end: number | null;
    kind: string;
    sequence: number;
  };
};

function excerptParts(text: string, start: number, end: number, context = 280) {
  const safeStart = Math.max(0, Math.min(start, text.length));
  const safeEnd = Math.max(safeStart, Math.min(end, text.length));
  const winStart = Math.max(0, safeStart - context);
  const winEnd = Math.min(text.length, safeEnd + context);
  return {
    prefixEllipsis: winStart > 0,
    suffixEllipsis: winEnd < text.length,
    before: text.slice(winStart, safeStart),
    highlight: text.slice(safeStart, safeEnd),
    after: text.slice(safeEnd, winEnd),
  };
}

export function DocumentSourcePageClient({
  workspaceId,
  documentId,
}: {
  workspaceId: string;
  documentId: string;
}) {
  const searchParams = useSearchParams();
  const highlight = Number(searchParams.get("highlight") ?? "NaN");
  const end = Number(searchParams.get("end") ?? "NaN");
  const episodeParam = searchParams.get("episode");

  const [data, setData] = useState<SourcePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const qs = new URLSearchParams();
        if (episodeParam) qs.set("episode", episodeParam);
        if (Number.isFinite(highlight)) qs.set("highlight", String(highlight));
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/documents/${documentId}/source?${qs.toString()}`,
          { cache: "no-store" },
        );
        const body = (await res.json()) as SourcePayload & { error?: { message?: string } };
        if (cancelled) return;
        if (!res.ok) {
          setError(body.error?.message ?? "Failed to load source");
          setData(null);
          return;
        }
        setData(body);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load source");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, documentId, episodeParam, highlight]);

  const parts = useMemo(() => {
    if (!data?.episode.text) return null;
    if (!Number.isFinite(highlight)) return null;
    const hiEnd = Number.isFinite(end) && end > highlight ? end : highlight + (data.episode.text.length > highlight ? 1 : 0);
    return excerptParts(data.episode.text, highlight, hiEnd);
  }, [data, highlight, end]);

  const backHref =
    data?.document.source_kind === "slack_conversation" && data.document.agent_id
      ? `/slack`
      : data?.document.source_kind === "north_conversation"
        ? `/conversations`
        : `/documents`;

  return (
    <div className="flex min-h-[520px] flex-col gap-4 p-2">
      <Link href={backHref} className="text-caption text-muted-foreground hover:text-foreground">
        ← Back
      </Link>

      {loading ? (
        <p className="text-caption text-muted-foreground" role="status">
          Loading source…
        </p>
      ) : null}
      {error ? (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-caption text-destructive">
          {error}
        </p>
      ) : null}

      {data ? (
        <>
          <header>
            <h1 className="text-h4 text-foreground">{data.document.original_filename}</h1>
            <p className="mt-1 text-caption text-muted-foreground">
              {data.document.source_kind.replace(/_/g, " ")} · {data.document.status.replace(/_/g, " ")}
              {data.episode.page_start != null ? ` · episode p.${data.episode.page_start}` : null}
            </p>
          </header>

          <section className="rounded-lg border border-border bg-card/80 p-4">
            <h2 className="text-p font-medium text-muted-foreground">Source excerpt</h2>
            {parts ? (
              <pre className="mt-3 whitespace-pre-wrap break-words font-regular text-p text-foreground">
                {parts.prefixEllipsis ? "…" : null}
                {parts.before}
                <mark className="rounded bg-caution/35 px-0.5 text-foreground">{parts.highlight}</mark>
                {parts.after}
                {parts.suffixEllipsis ? "…" : null}
              </pre>
            ) : (
              <pre className="mt-3 max-h-[min(60vh,640px)] overflow-auto whitespace-pre-wrap break-words font-regular text-p text-foreground">
                {data.episode.text}
              </pre>
            )}
          </section>

          <p className="text-caption text-muted-foreground">
            <Link
              href={documentEvidenceHref(documentId, {
                charStart: Number.isFinite(highlight) ? highlight : undefined,
                charEnd: Number.isFinite(end) ? end : undefined,
                episodeId: data.episode.id,
              })}
              className="text-link hover:underline"
            >
              Permalink
            </Link>
            {" · "}
            Episode {data.episode.sequence + 1} ({data.episode.kind})
          </p>
        </>
      ) : null}
    </div>
  );
}
