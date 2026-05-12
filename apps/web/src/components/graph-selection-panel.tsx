"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { EntityMergeDialog } from "@/components/entity-merge-dialog";
import { GraphEdgePopover, type IncidentEdge } from "@/components/graph-edge-popover";

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
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/graph/entities/${entityId}?neighbor_depth=1&neighbor_limit=40`,
        { cache: "no-store" },
      );
      const body = (await res.json()) as { entity?: EntityDetail; error?: { message?: string } };
      if (!res.ok || !body.entity) {
        setError(body.error?.message ?? "Failed to load entity");
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
      <aside className="border-l border-border-subtle bg-surface/90 p-3 text-caption text-red-300">
        {error}
        <button type="button" className="ml-2 underline" onClick={onClose}>
          Close
        </button>
      </aside>
    );
  }
  if (!detail) {
    return (
      <aside className="border-l border-border-subtle bg-surface/90 p-3 text-caption text-muted">
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
      className="max-h-[min(70vh,560px)] w-full overflow-y-auto rounded-md border border-border-subtle bg-surface/95 p-3 text-caption xl:max-w-sm xl:rounded-none xl:border-0 xl:border-l"
      aria-label="Entity details"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-body font-medium text-secondary">{detail.name}</p>
          <p className="text-muted">
            {detail.type}
            {detail.is_user_edited ? " · edited" : ""}
          </p>
        </div>
        <button type="button" className="text-muted underline" onClick={onClose}>
          Close
        </button>
      </div>
      {error ? <p className="mt-2 text-red-300">{error}</p> : null}
      <p className="mt-2 text-secondary">{detail.summary || "—"}</p>
      {detail.aliases?.length ? (
        <p className="mt-1 text-muted">Aliases: {detail.aliases.join(", ")}</p>
      ) : null}

      <section className="mt-4">
        <p className="font-medium text-secondary">Source notes</p>
        <ul className="mt-1 list-inside list-disc space-y-1 text-muted">
          {detail.source_notes?.length ? (
            detail.source_notes.map((n) => (
              <li key={n.id}>
                <Link className="text-accent-primary hover:underline" href={`/notes?note=${encodeURIComponent(n.id)}`}>
                  {n.title}
                </Link>{" "}
                <span className="text-muted">({n.origin})</span>
              </li>
            ))
          ) : (
            <li>None</li>
          )}
        </ul>
      </section>

      <section className="mt-4">
        <p className="font-medium text-secondary">Source documents / pages</p>
        <ul className="mt-1 space-y-2 text-muted">
          {detail.source_episodes?.length ? (
            detail.source_episodes.map((ep) => (
              <li key={ep.id}>
                <span className="text-secondary">{ep.document_name}</span>
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
        <p className="font-medium text-secondary">Neighbors</p>
        <ul className="mt-1 list-inside list-disc text-muted">
          {detail.neighbors_summary?.length ? (
            detail.neighbors_summary.map((n) => (
              <li key={n.id}>
                {n.name} <span className="text-muted">({n.type})</span>
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

      <div className="mt-4 flex flex-col gap-2 border-t border-border-subtle pt-3">
        <button
          type="button"
          className="rounded border border-border-strong px-2 py-1 text-left text-secondary hover:bg-surface"
          onClick={() => setMergeOpen(true)}
        >
          Merge with another entity…
        </button>
        <p className="text-muted">Ask about this — Sprint 6</p>
      </div>
    </aside>
    </>
  );
}
