"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

import { GraphCanvas } from "@/components/graph-canvas";
import { GraphCanvasErrorBoundary } from "@/components/graph-canvas-error-boundary";
import { GraphFilterBar, searchParamsToGraphFilters } from "@/components/graph-filter-bar";
import { GraphSelectionPanel } from "@/components/graph-selection-panel";
import { useGraphInvalidated } from "@/lib/graph-events";

type GraphPayload = {
  nodes: Array<{ id: string; name: string; type: string }>;
};

function AccessibleGraphList({
  workspaceId,
  filters,
  onPick,
}: {
  workspaceId: string;
  filters: Record<string, string | undefined>;
  onPick: (id: string) => void;
}) {
  const [data, setData] = useState<GraphPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const qs = useMemo(() => {
    const p = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => {
      if (v) p.set(k, v);
    });
    return p.toString();
  }, [filters]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(`/api/v1/workspaces/${workspaceId}/graph?${qs}`, { cache: "no-store" });
        const body = (await res.json()) as GraphPayload & { error?: { message?: string } };
        if (cancelled) return;
        if (!res.ok) {
          setError(body.error?.message ?? "Failed to load");
          setData(null);
          return;
        }
        setData({ nodes: body.nodes ?? [] });
        setError(null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, qs]);

  if (error) return <p className="text-caption text-red-300">{error}</p>;
  if (!data) return <p className="text-caption text-muted">Loading list…</p>;
  if (!data.nodes.length) return <p className="text-caption text-muted">No entities.</p>;
  return (
    <ul className="max-h-[360px] space-y-1 overflow-auto text-caption">
      {data.nodes.map((n) => (
        <li key={n.id}>
          <button
            type="button"
            className="w-full rounded px-2 py-1 text-left text-secondary hover:bg-surface"
            onClick={() => onPick(n.id)}
          >
            <span className="font-medium">{n.name}</span>{" "}
            <span className="text-muted">({n.type})</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function GraphWorkspaceInner({ workspaceId }: { workspaceId: string }) {
  const pathname = usePathname() ?? "/notes";
  const sp = useSearchParams();
  const filters = useMemo(() => searchParamsToGraphFilters(sp), [sp]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [listMode, setListMode] = useState(false);

  const [canvasBroken, setCanvasBroken] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mq.matches) setListMode(true);
  }, []);

  const bump = useCallback(() => setRefresh((n) => n + 1), []);

  useGraphInvalidated(() => {
    setSelectedId((current) => current);
    bump();
  });

  const showList = listMode || canvasBroken;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 xl:flex-row xl:items-start">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-title-3 text-secondary">Graph</p>
          <label className="flex items-center gap-2 text-caption text-muted">
            <input type="checkbox" checked={listMode} onChange={(e) => setListMode(e.target.checked)} />
            Accessible list
          </label>
        </div>
        <GraphFilterBar basePath={pathname} workspaceId={workspaceId} />
        {canvasBroken ? (
          <p className="text-caption text-amber-200/90">
            Graph canvas failed — using accessible list. Toggle “Accessible list” off to retry after refresh.
          </p>
        ) : null}
        {canvasBroken ? (
          <button
            type="button"
            className="self-start rounded border border-border-strong px-2 py-1 text-caption text-secondary hover:bg-surface"
            onClick={() => {
              setCanvasBroken(false);
              bump();
            }}
          >
            Retry graph canvas
          </button>
        ) : null}
        {showList ? (
          <AccessibleGraphList
            key={`list-${refresh}`}
            workspaceId={workspaceId}
            filters={filters}
            onPick={(id) => {
              setSelectedId(id);
              setListMode(false);
              setCanvasBroken(false);
            }}
          />
        ) : (
          <GraphCanvasErrorBoundary
            fallback={
              <AccessibleGraphList
                key={`fallback-list-${refresh}`}
                workspaceId={workspaceId}
                filters={filters}
                onPick={(id) => {
                  setSelectedId(id);
                  setCanvasBroken(false);
                }}
              />
            }
            onError={() => setCanvasBroken(true)}
          >
            <GraphCanvas
              key={refresh}
              workspaceId={workspaceId}
              filters={filters}
              onSelectNode={(id) => setSelectedId(id)}
            />
          </GraphCanvasErrorBoundary>
        )}
      </div>
      {selectedId ? (
        <div className="border-t border-border-subtle pt-2 xl:max-h-[min(70vh,560px)] xl:w-[min(100%,22rem)] xl:shrink-0 xl:border-l xl:border-t-0 xl:pl-3 xl:pt-0">
          <GraphSelectionPanel
            workspaceId={workspaceId}
            entityId={selectedId}
            onClose={() => setSelectedId(null)}
            onMerged={() => bump()}
          />
        </div>
      ) : null}
    </div>
  );
}

export function GraphWorkspacePanel({ workspaceId }: { workspaceId: string }) {
  return (
    <section
      aria-label="Graph panel"
      // ``flex-1`` lets the panel grow to fill the grid row when it has
      // the headroom (e.g. on /graph and on Notes/Chat side-by-side
      // layouts). ``min-h-[480px]`` is the floor for very short
      // viewports. Removed the previous fixed-height cap that caused the
      // empty band below the canvas.
      className="flex min-h-[480px] flex-1 flex-col rounded-lg border border-border-subtle bg-surface/80 p-4"
    >
      <Suspense fallback={<p className="text-caption text-muted">Loading graph panel…</p>}>
        <GraphWorkspaceInner workspaceId={workspaceId} />
      </Suspense>
    </section>
  );
}
