"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { EntityMergeDialog } from "@/components/entity-merge-dialog";
import { GraphEdgePopover, type IncidentEdge } from "@/components/graph-edge-popover";
import { readApiErrorMessage } from "@/lib/api-error-message";
import { documentEvidenceHref } from "@/lib/document-evidence-link";
import { fetchWithTimeout, readJsonResponse } from "@/lib/fetch-with-timeout";

type EvidenceRow = {
  id: string;
  document_id: string;
  document_filename: string;
  episode_id: string | null;
  page: number;
  char_start: number;
  char_end: number;
  quote: string;
  method: string;
  attributes: Record<string, string>;
};

function EvidenceSection({
  workspaceId,
  entityId,
  sourceNotes,
}: {
  workspaceId: string;
  entityId: string;
  sourceNotes?: Array<{ id: string; title: string; origin: string }>;
}) {
  const [rows, setRows] = useState<EvidenceRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setError(null);
    void (async () => {
      try {
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/graph/entities/${entityId}/evidence?limit=10`,
          { cache: "no-store" },
        );
        const body = (await res.json()) as {
          items?: EvidenceRow[];
          total?: number;
          error?: { message?: string };
        };
        if (cancelled) return;
        if (!res.ok) {
          setError(body.error?.message ?? "Failed to load evidence");
          setRows([]);
          return;
        }
        setRows(body.items ?? []);
        setTotal(body.total ?? 0);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to load evidence");
        setRows([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, entityId]);

  if (rows === null) {
    return (
      <section className="mt-4" aria-busy="true">
        <p className="font-medium text-muted-foreground">Evidence</p>
        <p className="mt-1 text-muted-foreground">Loading…</p>
      </section>
    );
  }

  return (
    <section className="mt-4" aria-label="Source evidence">
      <p className="font-medium text-muted-foreground">
        Evidence{total > rows.length ? <span className="text-muted-foreground"> · {total} total</span> : null}
      </p>
      {error ? <p className="mt-1 text-red-300">{error}</p> : null}
      {rows.length === 0 && !error ? (
        <div className="mt-1 space-y-2 text-muted-foreground">
          <p>
            No source passage quotes linked yet. Char-offset evidence is created during{" "}
            <strong className="font-medium text-foreground">Extract graph</strong> (LangExtract).
            Retry <strong className="font-medium text-foreground">Graph</strong> on the source in
            Documents, Conversations, or Slack — evidence is filled on the next successful extract
            run.
          </p>
          {sourceNotes && sourceNotes.length > 0 ? (
            <div>
              <p className="text-caption text-muted-foreground">Linked atomic notes (provenance):</p>
              <ul className="mt-1 space-y-1">
                {sourceNotes.slice(0, 8).map((n) => (
                  <li key={n.id}>
                    <Link
                      className="text-primary hover:underline"
                      href={`/notes?note=${encodeURIComponent(n.id)}`}
                    >
                      {n.title}
                    </Link>{" "}
                    <span className="text-muted-foreground">({n.origin})</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
      <ul className="mt-2 space-y-2">
        {rows.map((r) => (
          <li
            key={r.id}
            className="rounded border border-border bg-card/40 p-2"
          >
            <p className="text-muted-foreground">
              <span className="text-muted-foreground">{r.document_filename}</span>
              {r.page > 0 ? <span> · p.{r.page}</span> : null}
            </p>
            <blockquote className="mt-1 border-l-2 border-primary/60 pl-2 text-muted-foreground">
              {r.quote}
            </blockquote>
            <Link
              className="mt-1 inline-block text-foreground hover:underline"
              href={documentEvidenceHref(r.document_id, {
                page: r.page,
                charStart: r.char_start,
                charEnd: r.char_end,
                episodeId: r.episode_id,
              })}
            >
              View in document →
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

type EntityDetail = {
  id: string;
  type: string;
  name: string;
  summary: string;
  properties: Record<string, unknown>;
  aliases: string[];
  is_user_edited: boolean;
  source_notes: Array<{ id: string; title: string; origin: string }>;
  source_episodes: Array<{
    id: string;
    document_id: string;
    document_name: string;
    kind: string;
    text: string;
    page_start: number | null;
    page_end: number | null;
  }>;
  neighbors_summary: Array<{ id: string; type: string; name: string }>;
  incident_relationships?: IncidentEdge[];
};

export function GraphSelectionPanel({
  workspaceId,
  entityId,
  onClose,
  onMerged,
}: {
  workspaceId: string;
  entityId: string;
  onClose: () => void;
  onMerged: () => void;
}) {
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mergeOpen, setMergeOpen] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await fetchWithTimeout(
        `/api/v1/workspaces/${workspaceId}/graph/entities/${entityId}?neighbor_depth=1&neighbor_limit=40`,
        { cache: "no-store", timeoutMs: 30_000 },
      );
      const body = await readJsonResponse<{ entity?: EntityDetail }>(res);
      if (!res.ok || !body.entity) {
        setError(
          readApiErrorMessage(
            body,
            res.ok ? "Entity response was empty" : "Failed to load entity",
          ),
        );
        setDetail(null);
        return;
      }
      setDetail(body.entity);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
      setDetail(null);
    }
  }, [workspaceId, entityId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !detail) {
    return (
      <aside className="border-l border-border bg-card/90 p-3 text-caption text-red-300">
        {error}
        <button type="button" className="ml-2 underline" onClick={onClose}>
          Close
        </button>
      </aside>
    );
  }
  if (!detail) {
    return (
      <aside className="border-l border-border bg-card/90 p-3 text-caption text-muted-foreground">
        Loading…
      </aside>
    );
  }

  return (
    <>
      <EntityMergeDialog
        open={mergeOpen}
        workspaceId={workspaceId}
        survivorEntityId={entityId}
        onClose={() => setMergeOpen(false)}
        onMerged={() => {
          void load();
          onMerged();
        }}
      />
      <aside
      className="max-h-[min(70vh,560px)] w-full overflow-y-auto rounded-md border border-border bg-card/95 p-3 text-caption xl:max-w-sm xl:rounded-none xl:border-0 xl:border-l"
      aria-label="Entity details"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-p font-medium text-muted-foreground">{detail.name}</p>
          <p className="text-muted-foreground">
            {detail.type}
            {detail.is_user_edited ? " · edited" : ""}
          </p>
        </div>
        <button type="button" className="text-muted-foreground underline" onClick={onClose}>
          Close
        </button>
      </div>
      {error ? <p className="mt-2 text-red-300">{error}</p> : null}
      <p className="mt-2 text-muted-foreground">{detail.summary || "—"}</p>
      {detail.aliases?.length ? (
        <p className="mt-1 text-muted-foreground">Aliases: {detail.aliases.join(", ")}</p>
      ) : null}

      <section className="mt-4">
        <p className="font-medium text-muted-foreground">Source notes</p>
        <ul className="mt-1 list-inside list-disc space-y-1 text-muted-foreground">
          {detail.source_notes?.length ? (
            detail.source_notes.map((n) => (
              <li key={n.id}>
                <Link className="text-primary hover:underline" href={`/notes?note=${encodeURIComponent(n.id)}`}>
                  {n.title}
                </Link>{" "}
                <span className="text-muted-foreground">({n.origin})</span>
              </li>
            ))
          ) : (
            <li>None</li>
          )}
        </ul>
      </section>

        <EvidenceSection
          workspaceId={workspaceId}
          entityId={entityId}
          sourceNotes={detail.source_notes}
        />

      <section className="mt-4">
        <p className="font-medium text-muted-foreground">Source documents / pages</p>
        <ul className="mt-1 space-y-2 text-muted-foreground">
          {detail.source_episodes?.length ? (
            detail.source_episodes.map((ep) => (
              <li key={ep.id}>
                <span className="text-muted-foreground">{ep.document_name}</span>
                {ep.page_start != null ? (
                  <span>
                    {" "}
                    · p.{ep.page_start}
                    {ep.page_end != null && ep.page_end !== ep.page_start ? `–${ep.page_end}` : ""}
                  </span>
                ) : null}
              </li>
            ))
          ) : (
            <li>None</li>
          )}
        </ul>
      </section>

      <section className="mt-4">
        <p className="font-medium text-muted-foreground">Neighbors</p>
        <ul className="mt-1 list-inside list-disc text-muted-foreground">
          {detail.neighbors_summary?.length ? (
            detail.neighbors_summary.map((n) => (
              <li key={n.id}>
                {n.name} <span className="text-muted-foreground">({n.type})</span>
              </li>
            ))
          ) : (
            <li>—</li>
          )}
        </ul>
      </section>

      <GraphEdgePopover
        workspaceId={workspaceId}
        entityId={entityId}
        edges={detail.incident_relationships ?? []}
        onChanged={() => {
          void load();
          onMerged();
        }}
      />

      <div className="mt-4 flex flex-col gap-2 border-t border-border pt-3">
        <button
          type="button"
          className="rounded border border-input px-2 py-1 text-left text-muted-foreground hover:bg-card"
          onClick={() => setMergeOpen(true)}
        >
          Merge with another entity…
        </button>
        <p className="text-muted-foreground">Ask about this — Sprint 6</p>
      </div>
    </aside>
    </>
  );
}
