"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { GraphCanvas } from "@/components/graph-canvas";
import { GraphCanvasErrorBoundary } from "@/components/graph-canvas-error-boundary";
import { GraphLiveJobBridgeHost } from "@/components/graph-live-job-bridge";
import { GraphFilterBar, searchParamsToGraphFilters } from "@/components/graph-filter-bar";
import { GraphragCommunitySidebar } from "@/components/graphrag-community-sidebar";
import { GraphragEntityPanel } from "@/components/graphrag-entity-panel";
import { GraphragIndexControls, graphragJobId, type GraphragIndexRow } from "@/components/graphrag-index-controls";
import { MemorySpaceCompareStrip } from "@/components/memory-space-compare-strip";
import { GraphSelectionPanel } from "@/components/graph-selection-panel";
import { Button } from "@/components/ui/button";
import {
  graphBackendFromSearchParams,
  graphragIndexIdFromSearchParams,
  readGraphBackend,
  writeGraphBackend,
  type GraphBackend,
} from "@/lib/graph-backend";
import { useActiveJobs, useJobEvents } from "@/lib/job-events";
import { isGraphExtractionJobId } from "@/lib/arq-job-id";
import { useGraphInvalidated } from "@/lib/graph-events";
import { useGraphLiveDelta } from "@/lib/graph-live-delta";
import { usePipelineActivity } from "@/lib/pipeline-activity";
import { cn } from "@/lib/utils";

type GraphPayload = {
  nodes: Array<{ id: string; name: string; type: string }>;
};

function AccessibleGraphList({
  workspaceId,
  filters,
  graphBackend,
  graphragIndexId,
  onPick,
}: {
  workspaceId: string;
  filters: Record<string, string | undefined>;
  graphBackend: GraphBackend;
  graphragIndexId?: string | null;
  onPick: (id: string) => void;
}) {
  const [data, setData] = useState<GraphPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const qs = useMemo(() => {
    const p = new URLSearchParams();
    if (graphBackend === "graphrag") {
      p.set("backend", "graphrag");
      if (graphragIndexId) p.set("graphrag_index_id", graphragIndexId);
      if (filters.agent_id) p.set("agent_id", filters.agent_id);
      if (filters.collection_id) p.set("collection_id", filters.collection_id);
    } else {
      Object.entries(filters).forEach(([k, v]) => {
        if (v) p.set(k, v);
      });
    }
    return p.toString();
  }, [filters, graphBackend, graphragIndexId]);

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
  if (!data) return <p className="text-caption text-muted-foreground">Loading list…</p>;
  if (!data.nodes.length) return <p className="text-caption text-muted-foreground">No entities.</p>;
  return (
    <ul className="max-h-[360px] space-y-1 overflow-auto text-caption">
      {data.nodes.map((n) => (
        <li key={n.id}>
          <button
            type="button"
            className="w-full rounded px-2 py-1 text-left text-muted-foreground hover:bg-card"
            onClick={() => onPick(n.id)}
          >
            <span className="font-medium">{n.name}</span>{" "}
            <span className="text-muted-foreground">({n.type})</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function GraphWorkspaceInner({
  workspaceId,
  onCollapse,
  fullHeight = false,
  theaterMode = false,
}: {
  workspaceId: string;
  onCollapse?: () => void;
  fullHeight?: boolean;
  /** Compact graph panel for MiroFish-style theater split (live graph left). */
  theaterMode?: boolean;
}) {
  const pathname = usePathname() ?? "/notes";
  const router = useRouter();
  const sp = useSearchParams();
  const filters = useMemo(() => searchParamsToGraphFilters(sp), [sp]);
  const urlBackend = useMemo(() => graphBackendFromSearchParams(sp), [sp]);
  const urlIndexId = useMemo(() => graphragIndexIdFromSearchParams(sp), [sp]);
  const [backend, setBackend] = useState<GraphBackend>(() => urlBackend);
  const [graphragIndexId, setGraphragIndexId] = useState<string | null>(urlIndexId ?? null);
  const [activeGraphragIndex, setActiveGraphragIndex] = useState<GraphragIndexRow | null>(null);
  const compareMode = sp.get("compare") === "1";
  const [selectedCommunityId, setSelectedCommunityId] = useState<number | null>(null);
  const selectedAgentId = filters.agent_id ?? null;
  const selectedCollectionId = filters.collection_id ?? null;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [listMode, setListMode] = useState(false);
  const graphragBuildRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (urlBackend === "graphrag") {
      setBackend("graphrag");
    } else if (!sp.get("view") && !sp.get("backend")) {
      setBackend(readGraphBackend(workspaceId));
    }
  }, [urlBackend, sp, workspaceId]);

  useEffect(() => {
    if (urlIndexId) setGraphragIndexId(urlIndexId);
  }, [urlIndexId]);

  useEffect(() => {
    setSelectedId(null);
  }, [filters.agent_id, filters.collection_id, graphragIndexId, backend]);

  const syncUrl = useCallback(
    (
      nextBackend: GraphBackend,
      indexId: string | null,
      agentId?: string | null,
      collectionId?: string | null,
    ) => {
      const p = new URLSearchParams(sp.toString());
      if (nextBackend === "graphrag") {
        p.set("view", "graphrag");
        p.delete("backend");
        if (indexId) p.set("index_id", indexId);
        else p.delete("index_id");
        if (agentId !== undefined) {
          if (agentId) p.set("agent_id", agentId);
          else p.delete("agent_id");
        }
        if (collectionId !== undefined) {
          if (collectionId) p.set("collection_id", collectionId);
          else p.delete("collection_id");
        }
      } else {
        p.delete("view");
        p.delete("backend");
        p.delete("index_id");
        p.delete("graphrag_index_id");
      }
      router.replace(`${pathname}?${p.toString()}`, { scroll: false });
    },
    [pathname, router, sp],
  );

  const handleBackendChange = useCallback(
    (next: GraphBackend) => {
      setBackend(next);
      setSelectedId(null);
      writeGraphBackend(workspaceId, next);
      syncUrl(next, graphragIndexId);
      setRefresh((n) => n + 1);
    },
    [graphragIndexId, syncUrl, workspaceId],
  );

  const handleIndexChange = useCallback(
    (indexId: string | null, agentId: string | null, collectionId?: string | null) => {
      setGraphragIndexId(indexId);
      setSelectedId(null);
      if (backend === "graphrag") {
        syncUrl("graphrag", indexId, agentId, collectionId ?? null);
      }
      setRefresh((n) => n + 1);
    },
    [backend, syncUrl],
  );

  const registerGraphragBuild = useCallback((fn: () => void) => {
    graphragBuildRef.current = fn;
  }, []);

  const handleGraphitiCrossLink = useCallback(
    (graphitiEntityId: string) => {
      const p = new URLSearchParams(sp.toString());
      p.delete("view");
      p.delete("compare");
      if (selectedAgentId) p.set("agent_id", selectedAgentId);
      p.append("seed_entity_ids", graphitiEntityId);
      router.push(`${pathname}?${p.toString()}`);
      setBackend("graphiti");
      writeGraphBackend(workspaceId, "graphiti");
      setSelectedId(graphitiEntityId);
    },
    [pathname, router, selectedAgentId, sp, workspaceId],
  );

  const [canvasBroken, setCanvasBroken] = useState(false);
  const [liveIngestion, setLiveIngestion] = useState(false);
  const [graphPulse, setGraphPulse] = useState(false);
  const wasLiveRef = useRef(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mq.matches) setListMode(true);
  }, []);

  const graphragReady = activeGraphragIndex?.status === "ready";
  const graphragBuilding =
    activeGraphragIndex?.status === "pending" ||
    activeGraphragIndex?.status === "running";
  const graphragBlockedMessage = useMemo(() => {
    if (backend !== "graphrag" || graphragReady) return null;
    if (!activeGraphragIndex) {
      return "No GraphRAG index for this memory space. Build one using the toolbar above.";
    }
    if (graphragBuilding) {
      return "GraphRAG index is building — the graph will appear when the build completes.";
    }
    if (activeGraphragIndex.status === "failed") {
      return (
        activeGraphragIndex.failure_reason?.trim() ||
        "GraphRAG index build failed. Use Rebuild above or check the job log."
      );
    }
    return "GraphRAG index is not ready yet.";
  }, [activeGraphragIndex, backend, graphragBuilding, graphragReady]);

  const showGraphragCanvas =
    backend !== "graphrag" || graphragReady || compareMode;

  const bump = useCallback(() => setRefresh((n) => n + 1), []);

  const pulseGraph = useCallback(() => {
    setGraphPulse(true);
    window.setTimeout(() => setGraphPulse(false), 800);
  }, []);

  const activeJobs = useActiveJobs();
  const { registerActiveJob, requestOpenLogConsole } = useJobEvents();

  useGraphInvalidated(() => {
    if (!wasLiveRef.current) bump();
  });

  usePipelineActivity((payload) => {
    const stage = payload.stage ?? "";
    if (
      stage === "extracting_graph" ||
      stage === "building_graph" ||
      stage === "graphrag_indexing"
    ) {
      setLiveIngestion(true);
    }
    if (payload.graphTouch) pulseGraph();
  });

  useGraphLiveDelta(() => {
    setLiveIngestion(true);
    pulseGraph();
  });

  useEffect(() => {
    if (theaterMode) setLiveIngestion(true);
  }, [theaterMode]);

  useEffect(() => {
    if (theaterMode) return;
    const graphJobActive = activeJobs.some(
      (j) =>
        j.kind === "extract_graph" ||
        j.kind === "graphrag_index" ||
        isGraphExtractionJobId(j.jobId),
    );
    if (graphJobActive) setLiveIngestion(true);
    else if (wasLiveRef.current) setLiveIngestion(false);
  }, [activeJobs, theaterMode]);

  useEffect(() => {
    if (wasLiveRef.current && !liveIngestion) {
      bump();
    }
    wasLiveRef.current = liveIngestion;
  }, [liveIngestion, bump]);

  const showList = listMode || canvasBroken;

  return (
    // ``items-stretch`` (default) on the xl row keeps the canvas column
    // tall enough to fill the panel — the previous ``items-start`` capped
    // it at the canvas's natural ~420-480px floor and left a large blank
    // band on wide screens.
    <div
      className={cn(
        "flex min-h-0 flex-1 flex-col gap-2",
        (fullHeight || theaterMode) && "h-full",
        !theaterMode && "xl:flex-row",
      )}
    >
      <div
        className={cn(
          "flex min-h-0 min-w-0 flex-1 flex-col gap-2",
          (fullHeight || theaterMode) && "h-full",
        )}
      >
        {!theaterMode ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-h5 text-muted-foreground">Graph</p>
            <div
              className="inline-flex rounded-md border border-border bg-secondary/40 p-0.5"
              role="group"
              aria-label="Graph backend"
            >
              {(["graphiti", "graphrag"] as const).map((b) => (
                <button
                  key={b}
                  type="button"
                  onClick={() => handleBackendChange(b)}
                  className={cn(
                    "rounded px-2.5 py-1 text-caption font-medium transition",
                    backend === b
                      ? "bg-card text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {b === "graphiti" ? "Graphiti" : "GraphRAG"}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-caption text-muted-foreground">
              <input type="checkbox" checked={listMode} onChange={(e) => setListMode(e.target.checked)} />
              Accessible list
            </label>
            {onCollapse ? (
              <button
                type="button"
                onClick={onCollapse}
                title="Collapse graph panel"
                aria-label="Collapse graph panel"
                aria-expanded
                className="cursor-pointer rounded border border-border px-1.5 py-0.5 text-caption text-muted-foreground transition-colors duration-150 hover:bg-card hover:text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span aria-hidden="true">›</span>
              </button>
            ) : null}
          </div>
        </div>
        ) : (
          <div className="flex shrink-0 items-center justify-between gap-2">
            <p className="text-caption font-medium uppercase tracking-wider text-muted-foreground">
              Live graph
            </p>
            {liveIngestion ? (
              <span className="flex items-center gap-1.5 text-[10px] text-caution">
                <span className="relative flex h-1.5 w-1.5 motion-reduce:hidden" aria-hidden>
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-caution opacity-70" />
                  <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-caution" />
                </span>
                Updating
              </span>
            ) : null}
          </div>
        )}
        {!theaterMode ? (
          <MemorySpaceCompareStrip
            workspaceId={workspaceId}
            agentId={selectedAgentId}
            compact
          />
        ) : null}
        {!theaterMode && backend === "graphrag" ? (
          <GraphragIndexControls
            workspaceId={workspaceId}
            selectedAgentId={selectedAgentId}
            selectedCollectionId={selectedCollectionId}
            selectedIndexId={graphragIndexId}
            onIndexChange={handleIndexChange}
            onActiveIndexChange={setActiveGraphragIndex}
            onRegisterBuild={registerGraphragBuild}
            compact
          />
        ) : null}
        {!theaterMode && backend === "graphiti" ? (
          <GraphFilterBar basePath={pathname} workspaceId={workspaceId} />
        ) : null}
        {canvasBroken ? (
          <p className="text-caption text-amber-200/90">
            Graph canvas failed — using accessible list. Toggle “Accessible list” off to retry after refresh.
          </p>
        ) : null}
        {canvasBroken ? (
          <button
            type="button"
            className="self-start rounded border border-input px-2 py-1 text-caption text-muted-foreground hover:bg-card"
            onClick={() => {
              setCanvasBroken(false);
              bump();
            }}
          >
            Retry graph canvas
          </button>
        ) : null}
        {liveIngestion && !theaterMode ? (
          <div className="flex items-center gap-2 rounded-md border border-caution/40 bg-caution/10 px-2 py-1 text-caption text-foreground">
            <span className="relative flex h-2 w-2 motion-reduce:hidden" aria-hidden>
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-caution opacity-70" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-caution" />
            </span>
            Live ingestion — graph updating as entities and edges are extracted
          </div>
        ) : null}
        {compareMode && !theaterMode ? (
          <div className="flex min-h-0 flex-1 flex-col gap-2 xl:flex-row">
            <div className="flex min-h-[280px] flex-1 flex-col gap-1">
              <p className="text-caption font-medium text-muted-foreground">Graphiti (live)</p>
              <GraphFilterBar
                basePath={pathname}
                workspaceId={workspaceId}
                scopeHint="Graphiti only"
              />
              <GraphCanvas
                key={`compare-g-${refresh}`}
                workspaceId={workspaceId}
                filters={filters}
                graphBackend="graphiti"
                fullHeight={fullHeight}
                liveIngestion={liveIngestion}
                onSelectNode={() => {}}
              />
            </div>
            <div className="flex min-h-[280px] flex-1 flex-col gap-1">
              <p className="text-caption font-medium text-muted-foreground">
                MS GraphRAG (index snapshot)
              </p>
              <GraphragIndexControls
                workspaceId={workspaceId}
                selectedAgentId={selectedAgentId}
                selectedCollectionId={selectedCollectionId}
                selectedIndexId={graphragIndexId}
                onIndexChange={handleIndexChange}
                onActiveIndexChange={setActiveGraphragIndex}
                compact
              />
              {graphragReady && graphragIndexId ? (
                <GraphCanvas
                  key={`compare-r-${refresh}-${graphragIndexId}-${selectedCommunityId ?? ""}`}
                  workspaceId={workspaceId}
                  filters={filters}
                  graphBackend="graphrag"
                  graphragIndexId={graphragIndexId}
                  communityId={selectedCommunityId}
                  fullHeight={fullHeight}
                  onSelectNode={(id) => setSelectedId(id)}
                />
              ) : (
                <p className="text-caption text-muted-foreground">
                  {graphragBlockedMessage ??
                    "Build a GraphRAG index for this memory space to compare side-by-side."}
                </p>
              )}
            </div>
          </div>
        ) : showList ? (
          <AccessibleGraphList
            key={`list-${refresh}-${backend}`}
            workspaceId={workspaceId}
            filters={filters}
            graphBackend={backend}
            graphragIndexId={graphragIndexId}
            onPick={(id) => {
              setSelectedId(id);
              setListMode(false);
              setCanvasBroken(false);
            }}
          />
        ) : !showGraphragCanvas && graphragBlockedMessage ? (
          <div className="flex min-h-[280px] flex-1 flex-col items-start justify-center rounded-md border border-border bg-secondary/20 px-4 py-6">
            <p className="text-p font-medium text-foreground">GraphRAG snapshot unavailable</p>
            <p className="mt-2 max-w-lg text-caption text-muted-foreground">
              {graphragBlockedMessage}
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                onClick={() => graphragBuildRef.current?.()}
              >
                {activeGraphragIndex?.status === "failed" ||
                activeGraphragIndex?.status === "ready"
                  ? "Rebuild index"
                  : activeGraphragIndex?.status === "pending" ||
                      activeGraphragIndex?.status === "running"
                    ? "Start new build"
                    : "Build index"}
              </Button>
              {activeGraphragIndex &&
              (activeGraphragIndex.status === "failed" ||
                activeGraphragIndex.status === "running" ||
                activeGraphragIndex.status === "pending") ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    const id = activeGraphragIndex.id;
                    registerActiveJob(graphragJobId(id), workspaceId, null, "graphrag_index");
                    requestOpenLogConsole();
                  }}
                >
                  View build log
                </Button>
              ) : null}
            </div>
            {activeGraphragIndex?.status === "failed" ? (
              <p className="mt-3 text-caption text-muted-foreground">
                Live Graphiti graph may still have entities — switch to Graphiti or use Split
                compare once an index is ready.
              </p>
            ) : null}
          </div>
        ) : (
          <GraphCanvasErrorBoundary
            fallback={
              <AccessibleGraphList
                key={`fallback-list-${refresh}-${backend}`}
                workspaceId={workspaceId}
                filters={filters}
                graphBackend={backend}
                graphragIndexId={graphragIndexId}
                onPick={(id) => {
                  setSelectedId(id);
                  setCanvasBroken(false);
                }}
              />
            }
            onError={() => setCanvasBroken(true)}
          >
            <div
              className={cn(
                "flex min-h-[320px] flex-1 flex-col",
                (fullHeight || theaterMode) && "min-h-0",
                graphPulse && "rounded-lg shadow-[inset_0_0_0_2px_rgba(250,204,21,0.45)] transition-shadow duration-500 motion-reduce:transition-none",
              )}
            >
              <GraphCanvas
                key={`${refresh}-${backend}-${graphragIndexId ?? ""}-${selectedCommunityId ?? ""}`}
                workspaceId={workspaceId}
                filters={filters}
                graphBackend={backend}
                graphragIndexId={graphragIndexId}
                communityId={selectedCommunityId}
                fullHeight={fullHeight || theaterMode}
                liveIngestion={backend === "graphiti" && liveIngestion}
                onLivePatch={pulseGraph}
                onSelectNode={(id) => setSelectedId(id)}
              />
            </div>
          </GraphCanvasErrorBoundary>
        )}
      </div>
      {backend === "graphrag" && !theaterMode && !compareMode ? (
        <GraphragCommunitySidebar
          workspaceId={workspaceId}
          graphragIndexId={graphragIndexId}
          agentId={selectedAgentId}
          selectedCommunityId={selectedCommunityId}
          onSelectCommunity={(id) => {
            setSelectedCommunityId(id);
            setRefresh((n) => n + 1);
          }}
        />
      ) : null}
      {selectedId && !theaterMode && backend === "graphiti" && !compareMode ? (
        // Side panel keeps an explicit height cap on wide screens so its
        // internal scroll area stays predictable even though the parent
        // row now stretches to the panel height.
        <div className="border-t border-border pt-2 xl:w-[min(100%,22rem)] xl:shrink-0 xl:overflow-auto xl:border-l xl:border-t-0 xl:pl-3 xl:pt-0">
          <GraphSelectionPanel
            workspaceId={workspaceId}
            entityId={selectedId}
            onClose={() => setSelectedId(null)}
            onMerged={() => bump()}
          />
        </div>
      ) : null}
      {selectedId && !theaterMode && backend === "graphrag" && !compareMode ? (
        <div className="border-t border-border pt-2 xl:w-[min(100%,22rem)] xl:shrink-0 xl:overflow-auto xl:border-l xl:border-t-0 xl:pl-3 xl:pt-0">
          <GraphragEntityPanel
            workspaceId={workspaceId}
            entityId={selectedId}
            graphragIndexId={graphragIndexId}
            agentId={selectedAgentId}
            onClose={() => setSelectedId(null)}
            onSelectCommunity={(c) => {
              setSelectedCommunityId(c);
              setRefresh((n) => n + 1);
            }}
            onGraphitiMatch={handleGraphitiCrossLink}
          />
        </div>
      ) : null}
    </div>
  );
}

export function GraphWorkspacePanel({
  workspaceId,
  onCollapse,
  fullHeight = false,
  theaterMode = false,
}: {
  workspaceId: string;
  onCollapse?: () => void;
  /** When true (dedicated /graph page), stretch canvas to fill viewport height. */
  fullHeight?: boolean;
  theaterMode?: boolean;
}) {
  return (
    <section
      aria-label="Graph panel"
      className={cn(
        "flex min-h-0 flex-col rounded-lg border border-border bg-card/80",
        theaterMode ? "h-full flex-1 p-2" : "h-full flex-1 p-3",
        !fullHeight && !theaterMode && "min-h-[480px]",
      )}
    >
      <GraphLiveJobBridgeHost workspaceId={workspaceId} />
      <Suspense
        fallback={
          <p className="text-caption text-muted-foreground">Loading graph panel…</p>
        }
      >
        <div className={cn("flex min-h-0 flex-1 flex-col", (fullHeight || theaterMode) && "h-full")}>
          <GraphWorkspaceInner
            workspaceId={workspaceId}
            onCollapse={onCollapse}
            fullHeight={fullHeight}
            theaterMode={theaterMode}
          />
        </div>
      </Suspense>
    </section>
  );
}
