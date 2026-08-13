"use client";

import "@react-sigma/core/lib/style.css";

import { useCallback, useEffect, useMemo, useState } from "react";
import EdgeCurveProgram from "@sigma/edge-curve";
import { NodeBorderProgram } from "@sigma/node-border";
import {
  SigmaContainer,
  useLoadGraph,
  useRegisterEvents,
  useSigma,
} from "@react-sigma/core";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import louvain from "graphology-communities-louvain";

import { LiveGraphPatcher } from "@/components/graph-live-patcher";
import { readApiErrorMessage } from "@/lib/api-error-message";
import { fetchTimeoutMessage, fetchWithTimeout, readJsonResponse } from "@/lib/fetch-with-timeout";
import {
  applyCurvedEdgeRendering,
  colorForType,
  communityColor,
  EDGE_DEFAULT_SIZE,
  GRAPH_CANVAS_BG,
  GRAPH_CANVAS_BG_SIZE,
  NODE_BORDER_COLOR,
  NODE_BORDER_SIZE,
  nodeSizeForDegree,
  edgeColorForDensity,
} from "@/lib/graph-visual-style";
import { cn } from "@/lib/utils";

export type GraphNode = {
  id: string;
  type: string;
  name: string;
  summary: string;
  properties: Record<string, unknown>;
  aliases: string[];
  is_user_edited: boolean;
  /** MS GraphRAG native community id (when backend=graphrag). */
  community?: number;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  fact: string;
  valid_from: string | null;
  valid_to: string | null;
  confidence: number;
  origin: string;
  is_user_edited: boolean;
};

export type GraphPayload = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
};

/** Stable empty payload for live-ingestion patching (avoids GraphLoader reset). */
const EMPTY_LIVE_CANVAS: GraphPayload = { nodes: [], edges: [], truncated: false };

type ChipFilters = {
  entity_types: string[];
  edge_types: string[];
  tag: string;
};

function matchesNodeChipFilters(
  node: { type: string },
  chips: ChipFilters,
): boolean {
  if (chips.entity_types.length > 0 && !chips.entity_types.includes(node.type)) {
    return false;
  }
  return true;
}

function matchesEdgeChipFilters(
  edge: { type: string },
  chips: ChipFilters,
): boolean {
  if (chips.edge_types.length > 0 && !chips.edge_types.includes(edge.type)) {
    return false;
  }
  return true;
}

function ChipFilterApplier({
  data,
  chipFilters,
}: {
  data: GraphPayload;
  chipFilters: ChipFilters;
}) {
  const sigma = useSigma();
  useEffect(() => {
    const g = sigma.getGraph();
    if (!g) return;
    const nodeTypeById = new Map(data.nodes.map((n) => [n.id, n.type]));
    g.forEachNode((id) => {
      const t = nodeTypeById.get(id) ?? "";
      const hidden = !matchesNodeChipFilters({ type: t }, chipFilters);
      g.setNodeAttribute(id, "hidden", hidden);
    });
    const edgeTypeById = new Map(data.edges.map((e) => [e.id, e.type]));
    g.forEachEdge((id) => {
      const t = edgeTypeById.get(id) ?? "";
      const hidden = !matchesEdgeChipFilters({ type: t }, chipFilters);
      g.setEdgeAttribute(id, "hidden", hidden);
    });
    sigma.refresh();
  }, [sigma, data, chipFilters]);
  return null;
}

/**
 * Hover emphasis + readable HTML inspector. Sigma's WebGL labels are too
 * small for peripheral nodes; we dim the graph and show a high-contrast
 * overlay instead of force-rendering tiny canvas text.
 */
function GraphInteractionLayer({
  nodes,
  edges,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
}) {
  const sigma = useSigma();
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);
  const [inspector, setInspector] = useState<{
    kind: "node" | "edge";
    title: string;
    subtitle?: string;
    detail?: string;
  } | null>(null);

  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const edgeById = useMemo(() => new Map(edges.map((e) => [e.id, e])), [edges]);

  useEffect(() => {
    let neighborSet: Set<string> | null = null;
    const g = sigma.getGraph();

    if (hoveredNode && g.hasNode(hoveredNode)) {
      neighborSet = new Set(g.neighbors(hoveredNode));
      neighborSet.add(hoveredNode);
    } else if (hoveredEdge && g.hasEdge(hoveredEdge)) {
      const [source, target] = g.extremities(hoveredEdge);
      neighborSet = new Set([source, target]);
    }

    sigma.setSetting("nodeReducer", (node, attrs) => {
      if (!neighborSet) return { ...attrs, label: attrs.labelHidden ? "" : attrs.label };
      if (neighborSet.has(node)) {
        return {
          ...attrs,
          label: "",
          zIndex: 2,
        };
      }
      return {
        ...attrs,
        color: "rgba(148, 163, 184, 0.15)",
        label: "",
        zIndex: 0,
      };
    });

    sigma.setSetting("edgeReducer", (edge, attrs) => {
      if (!hoveredNode && !hoveredEdge) return attrs;
      if (hoveredEdge && edge === hoveredEdge) {
        return {
          ...attrs,
          color: "rgba(244, 114, 182, 0.95)",
          size: Math.max(attrs.size ?? 1, 0.65),
          zIndex: 3,
        };
      }
      if (hoveredNode) {
        const [source, target] = g.extremities(edge);
        const incident = source === hoveredNode || target === hoveredNode;
        if (incident) {
          return {
            ...attrs,
            color: "rgba(244, 114, 182, 0.92)",
            size: Math.max(attrs.size ?? 1, 0.55),
            zIndex: 2,
          };
        }
      }
      if (hoveredEdge) {
        const [source, target] = g.extremities(hoveredEdge);
        const [s, t] = g.extremities(edge);
        const incident = s === source || s === target || t === source || t === target;
        if (incident) {
          return {
            ...attrs,
            color: "rgba(244, 114, 182, 0.75)",
            size: Math.max(attrs.size ?? 1, 0.5),
            zIndex: 2,
          };
        }
      }
      return {
        ...attrs,
        color: "rgba(148, 163, 184, 0.08)",
        zIndex: 0,
      };
    });

    sigma.refresh();
  }, [sigma, hoveredNode, hoveredEdge]);

  const registerEvents = useRegisterEvents();
  useEffect(() => {
    registerEvents({
      enterNode: (event: { node: string }) => {
        setHoveredEdge(null);
        setHoveredNode(event.node);
        const n = nodeById.get(event.node);
        const g = sigma.getGraph();
        const attrs = g.hasNode(event.node) ? g.getNodeAttributes(event.node) : null;
        setInspector({
          kind: "node",
          title: n?.name ?? String(attrs?.fullLabel ?? attrs?.label ?? event.node),
          subtitle: n?.type ?? String(attrs?.entityType ?? "Entity"),
          detail: n?.summary?.trim() ? truncate(n.summary, 160) : undefined,
        });
      },
      leaveNode: () => {
        setHoveredNode(null);
        setInspector(null);
      },
      enterEdge: (event: { edge: string }) => {
        setHoveredNode(null);
        setHoveredEdge(event.edge);
        const e = edgeById.get(event.edge);
        const g = sigma.getGraph();
        if (!e || !g.hasEdge(event.edge)) {
          setInspector({ kind: "edge", title: "Relationship" });
          return;
        }
        const [source, target] = g.extremities(event.edge);
        const sourceName = nodeById.get(source)?.name ?? source.slice(0, 8);
        const targetName = nodeById.get(target)?.name ?? target.slice(0, 8);
        setInspector({
          kind: "edge",
          title: e.type || "RELATED_TO",
          subtitle: `${sourceName} → ${targetName}`,
          detail: e.fact?.trim() ? truncate(e.fact, 200) : undefined,
        });
      },
      leaveEdge: () => {
        setHoveredEdge(null);
        setInspector(null);
      },
    });
  }, [registerEvents, nodeById, edgeById, sigma]);

  if (!inspector) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none absolute inset-x-3 top-3 z-20 mx-auto max-w-lg rounded-lg border border-border bg-popover/95 px-3 py-2.5 shadow-lg backdrop-blur-sm"
    >
      <div className="flex items-start gap-2">
        <span
          aria-hidden
          className={cn(
            "mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            inspector.kind === "node"
              ? "bg-sky-500/20 text-sky-200"
              : "bg-pink-500/20 text-pink-200",
          )}
        >
          {inspector.kind === "node" ? inspector.subtitle ?? "Entity" : "Edge"}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold leading-snug text-foreground">{inspector.title}</p>
          {inspector.kind === "edge" && inspector.subtitle ? (
            <p className="mt-0.5 text-xs font-medium text-muted-foreground">{inspector.subtitle}</p>
          ) : null}
          {inspector.detail ? (
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{inspector.detail}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return `${s.slice(0, n - 1)}…`;
}

/**
 * Bottom-left legend. When the graph has meaningful entity-type diversity
 * we show types. When the graph collapses to a single type (the common
 * case with current Graphiti, which labels everything "Concept") we show
 * the Louvain community palette instead so the user has a key for what
 * the colors mean.
 *
 * Computes everything from ``data`` directly so it doesn't race the
 * async ForceAtlas2 layout that GraphLoader runs.
 */
function GraphLegend({
  data,
  useNativeCommunities = false,
}: {
  data: GraphPayload;
  useNativeCommunities?: boolean;
}) {
  const { mode, entries } = useMemo(() => {
    if (data.nodes.length === 0) {
      return { mode: "types" as const, entries: [] };
    }

    const nativeCount = data.nodes.filter((n) => n.community != null).length;
    if (useNativeCommunities && nativeCount > data.nodes.length * 0.5) {
      const byComm = new Map<number, { count: number; topName: string; topDeg: number }>();
      const degree = new Map<string, number>();
      for (const e of data.edges) {
        if (e.source === e.target) continue;
        degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
        degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
      }
      for (const n of data.nodes) {
        if (n.community == null) continue;
        const c = n.community;
        const cur = byComm.get(c) ?? { count: 0, topName: n.name, topDeg: 0 };
        cur.count += 1;
        const d = degree.get(n.id) ?? 0;
        if (d >= cur.topDeg) {
          cur.topDeg = d;
          cur.topName = n.name;
        }
        byComm.set(c, cur);
      }
      return {
        mode: "communities" as const,
        entries: Array.from(byComm.entries())
          .sort((a, b) => b[1].count - a[1].count)
          .slice(0, 10)
          .map(([cidx, info]) => ({
            key: `gr:${cidx}`,
            label: truncate(info.topName, 28),
            color: communityColor(cidx),
            count: info.count,
          })),
      };
    }

    // Count entity types up front. If there's real diversity (>= 2 types),
    // the legend stays type-based for familiarity.
    const typeCounts = new Map<string, number>();
    for (const n of data.nodes) {
      typeCounts.set(n.type, (typeCounts.get(n.type) ?? 0) + 1);
    }

    if (typeCounts.size >= 2) {
      return {
        mode: "types" as const,
        entries: Array.from(typeCounts.entries())
          .sort((a, b) => b[1] - a[1])
          .slice(0, 10)
          .map(([t, count]) => ({
            key: `type:${t}`,
            label: t,
            color: colorForType(t),
            count,
          })),
      };
    }

    // Single-type case: build a lightweight graph and run Louvain just
    // for the legend (it's <10ms for 240 nodes; identical params as the
    // main render so the colors line up).
    const g = new Graph({ type: "undirected", allowSelfLoops: true });
    for (const n of data.nodes) g.addNode(n.id, { label: n.name });
    for (const e of data.edges) {
      if (e.source === e.target) continue;
      if (!g.hasNode(e.source) || !g.hasNode(e.target)) continue;
      if (g.hasEdge(e.source, e.target)) continue;
      g.addEdge(e.source, e.target);
    }
    if (g.size === 0) {
      return { mode: "types" as const, entries: [] };
    }

    let partition: Record<string, number | string>;
    try {
      partition = louvain(g, { resolution: 1.0 }) as Record<string, number | string>;
    } catch {
      return { mode: "types" as const, entries: [] };
    }

    const seen = new Map<number | string, number>();
    const communityIdx = new Map<string, number>();
    for (const [id, c] of Object.entries(partition)) {
      let idx = seen.get(c);
      if (idx === undefined) {
        idx = seen.size;
        seen.set(c, idx);
      }
      communityIdx.set(id, idx);
    }

    const degree = new Map<string, number>();
    for (const e of data.edges) {
      if (e.source === e.target) continue;
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    }
    const nameById = new Map(data.nodes.map((n) => [n.id, n.name]));
    const topByCommunity = new Map<number, { name: string; deg: number }>();
    const countByCommunity = new Map<number, number>();
    Array.from(communityIdx.entries()).forEach(([id, idx]) => {
      countByCommunity.set(idx, (countByCommunity.get(idx) ?? 0) + 1);
      const d = degree.get(id) ?? 0;
      const cur = topByCommunity.get(idx);
      if (!cur || d > cur.deg) {
        topByCommunity.set(idx, { name: nameById.get(id) ?? id, deg: d });
      }
    });

    return {
      mode: "communities" as const,
      entries: Array.from(countByCommunity.entries())
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10)
        .map(([idx, count]) => ({
          key: `c:${idx}`,
          label: truncate(topByCommunity.get(idx)?.name ?? `Cluster ${idx + 1}`, 28),
          color: communityColor(idx),
          count,
        })),
    };
  }, [data, useNativeCommunities]);

  if (entries.length === 0) return null;

  return (
    <div
      aria-label={mode === "types" ? "Entity type legend" : "Cluster legend"}
      className="pointer-events-none absolute bottom-3 left-3 z-10 max-w-[18rem] rounded-md border border-border bg-popover/90 px-2.5 py-2 backdrop-blur"
    >
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {mode === "types" ? "Entity types" : "Clusters · top node shown"}
      </p>
      <ul className="flex flex-col gap-1">
        {entries.map((e) => (
          <li
            key={e.key}
            className="flex items-center gap-2 text-[11px] text-muted-foreground"
          >
            <span
              aria-hidden="true"
              className="h-2 w-2 flex-shrink-0 rounded-full"
              style={{ backgroundColor: e.color }}
            />
            <span className="truncate">{e.label}</span>
            <span className="ml-auto text-muted-foreground">{e.count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ZoomControl({ icon, label, onClick }: { icon: string; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className="flex h-7 w-7 cursor-pointer items-center justify-center rounded border border-input bg-popover/90 text-muted-foreground backdrop-blur transition-colors duration-150 hover:bg-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className="h-3.5 w-3.5"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {icon === "in" ? (
          <>
            <circle cx="11" cy="11" r="7" />
            <path d="m21 21-4.3-4.3" />
            <path d="M11 8v6M8 11h6" />
          </>
        ) : icon === "out" ? (
          <>
            <circle cx="11" cy="11" r="7" />
            <path d="m21 21-4.3-4.3" />
            <path d="M8 11h6" />
          </>
        ) : (
          <>
            <path d="M3 12a9 9 0 1 0 9-9" />
            <path d="M3 4v5h5" />
          </>
        )}
      </svg>
    </button>
  );
}

/**
 * Sprint 6 / layout-fix: explicit camera fit + container resize handling.
 *
 * Two failure modes this component repairs:
 * 1. **Initial load**: ``GraphLoader`` runs ForceAtlas2 in a worker for
 *    several seconds, then calls ``loadGraph()``. By the time the
 *    positioned graph lands, the SigmaContainer may have rendered while
 *    the parent flex column was still mid-layout — Sigma's camera defaults
 *    to a position that doesn't cover the new node bounding box, so all
 *    the nodes appear clustered at the top edge of the canvas.
 * 2. **Container resize**: when the user expands the embedded log, opens
 *    the selection panel, or toggles the Documents column, the canvas
 *    resizes. Sigma's built-in ResizeObserver refreshes the WebGL
 *    viewport but **does not reset the camera**, so the previously-fit
 *    bounding box becomes a tiny corner of the larger canvas.
 *
 * ``cam.animatedReset()`` recomputes the camera to fit all visible nodes
 * inside the current container.
 */
function CameraFitAndResize({ epoch }: { epoch: string }) {
  const sigma = useSigma();

  // Fit-on-data: every time GraphLoader replaces the underlying graph,
  // bump the camera to fit. We watch ``epoch`` rather than the graph
  // contents so the reset fires exactly once per load instead of on every
  // hover-driven reducer mutation.
  useEffect(() => {
    if (!sigma) return;
    // Defer two frames so React has committed the measured pixel size and
    // Sigma has applied the new graph before fitting. One frame was not
    // enough when Chrome devtools was closed: Sigma's internal canvases
    // could still have their stale tiny height, making the graph render
    // as a horizontal line.
    let inner = 0;
    const outer = window.requestAnimationFrame(() => {
      inner = window.requestAnimationFrame(() => {
        sigma.resize(true);
        sigma.refresh();
        const cam = sigma.getCamera();
        cam.animatedReset({ duration: 0 });
      });
    });
    return () => {
      window.cancelAnimationFrame(outer);
      if (inner) window.cancelAnimationFrame(inner);
    };
  }, [sigma, epoch]);

  // Fit-on-resize: observe the canvas container and reset whenever the
  // pixel size changes by more than a trivial amount. The 24px gate
  // avoids over-firing on sub-pixel layout passes.
  useEffect(() => {
    if (!sigma) return;
    const container = sigma.getContainer();
    if (!container) return;
    let lastW = container.clientWidth;
    let lastH = container.clientHeight;
    let raf = 0;
    const ro = new ResizeObserver(() => {
      const w = container.clientWidth;
      const h = container.clientHeight;
      if (Math.abs(w - lastW) < 24 && Math.abs(h - lastH) < 24) return;
      lastW = w;
      lastH = h;
      if (raf) window.cancelAnimationFrame(raf);
      raf = window.requestAnimationFrame(() => {
        sigma.resize(true);
        sigma.refresh();
        sigma.getCamera().animatedReset({ duration: 0 });
      });
    });
    ro.observe(container);
    return () => {
      ro.disconnect();
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, [sigma]);

  return null;
}

type CanvasSize = { width: number; height: number };

function useMeasuredCanvasFrame() {
  const [node, setNode] = useState<HTMLDivElement | null>(null);
  const [size, setSize] = useState<CanvasSize | null>(null);

  useEffect(() => {
    if (!node) return;

    let raf = 0;
    const measure = () => {
      const rect = node.getBoundingClientRect();
      const width = Math.max(1, Math.floor(rect.width));
      const height = Math.max(1, Math.floor(rect.height));
      // Do not mount Sigma while the flex grid is still effectively
      // collapsed. Mounting against a 1px-tall canvas is the root cause of
      // the "all graph objects render as a single line" regression.
      //
      // Important: this hook uses a callback ref and depends on `node`
      // because the first render often returns "Loading graph…" and does
      // not mount the canvas frame at all. The previous ref.current + []
      // effect ran once against null and never observed the real node,
      // leaving the UI stuck on "Preparing graph canvas…".
      if (width < 120 || height < 240) return;
      setSize((prev) => {
        if (prev && prev.width === width && prev.height === height) return prev;
        return { width, height };
      });
    };

    const schedule = () => {
      if (raf) window.cancelAnimationFrame(raf);
      raf = window.requestAnimationFrame(measure);
    };

    // Measure immediately and then once more after layout/paint. The second
    // pass catches the common route-transition case where flex children get
    // their final height one frame after mount.
    measure();
    raf = window.requestAnimationFrame(measure);

    const ro = new ResizeObserver(schedule);
    ro.observe(node);
    window.addEventListener("resize", schedule);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", schedule);
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, [node]);

  return { ref: setNode, size };
}

function ZoomControls() {
  const sigma = useSigma();
  return (
    <div className="pointer-events-auto absolute right-3 top-3 z-10 flex flex-col gap-1">
      <ZoomControl
        icon="in"
        label="Zoom in"
        onClick={() => {
          const cam = sigma.getCamera();
          cam.animatedZoom({ duration: 200 });
        }}
      />
      <ZoomControl
        icon="out"
        label="Zoom out"
        onClick={() => {
          const cam = sigma.getCamera();
          cam.animatedUnzoom({ duration: 200 });
        }}
      />
      <ZoomControl
        icon="reset"
        label="Reset view"
        onClick={() => {
          const cam = sigma.getCamera();
          cam.animatedReset({ duration: 250 });
        }}
      />
    </div>
  );
}

function normalizeGraphCoordinates(g: Graph): void {
  if (g.order === 0) return;

  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;

  g.forEachNode((_id, attrs) => {
    const x = typeof attrs.x === "number" ? attrs.x : 0;
    const y = typeof attrs.y === "number" ? attrs.y : 0;
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    minY = Math.min(minY, y);
    maxY = Math.max(maxY, y);
  });

  const width = maxX - minX;
  const height = maxY - minY;
  if (!Number.isFinite(width) || !Number.isFinite(height)) return;

  // Sigma's default camera is calibrated for graph coordinates around
  // [0, 1] (see the official examples that use random x/y in unit space).
  // ForceAtlas2 emits arbitrary-world coordinates (hundreds of units for
  // our current graph). If we then call camera.reset(), the camera resets
  // to unit-space while the graph remains in world-space, which visually
  // clips the graph into a thin line at the canvas edge. Normalize the
  // final layout into a padded unit box before handing it to Sigma.
  const span = Math.max(width, height, 1e-6);
  const padding = 0.08;
  const scale = (1 - padding * 2) / span;
  const offsetX = (1 - width * scale) / 2;
  const offsetY = (1 - height * scale) / 2;

  g.forEachNode((id, attrs) => {
    const x = typeof attrs.x === "number" ? attrs.x : 0;
    const y = typeof attrs.y === "number" ? attrs.y : 0;
    g.setNodeAttribute(id, "x", offsetX + (x - minX) * scale);
    g.setNodeAttribute(id, "y", offsetY + (y - minY) * scale);
  });
}

function GraphLoader({
  data,
  reducedMotion,
  useNativeCommunities = false,
  onSelectNode,
  onLoaded,
}: {
  data: GraphPayload;
  reducedMotion: boolean;
  useNativeCommunities?: boolean;
  onSelectNode: (id: string | null) => void;
  onLoaded?: () => void;
}) {
  const loadGraph = useLoadGraph();

  useEffect(() => {
    const g = new Graph({ type: "directed", allowSelfLoops: true });

    // First pass — pre-compute undirected degree so we can size nodes by
    // hub-ness. We also track per-node degree for the edge-alpha pass.
    const degree = new Map<string, number>();
    for (const e of data.edges) {
      if (e.source === e.target) continue;
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    }
    let maxDegree = 0;
    Array.from(degree.values()).forEach((d) => {
      if (d > maxDegree) maxDegree = d;
    });

    for (const n of data.nodes) {
      const nativeComm =
        useNativeCommunities && n.community != null ? n.community : undefined;
      g.addNode(n.id, {
        label: n.name,
        type: "border",
        size: nodeSizeForDegree(degree.get(n.id) ?? 0, maxDegree),
        color:
          nativeComm != null ? communityColor(nativeComm) : colorForType(n.type),
        borderColor: NODE_BORDER_COLOR,
        borderSize: NODE_BORDER_SIZE,
        entityType: n.type,
        fullLabel: n.name,
        summary: n.summary,
        community: nativeComm,
      });
    }

    for (const e of data.edges) {
      if (!g.hasNode(e.source) || !g.hasNode(e.target)) continue;
      if (g.hasEdge(e.id)) continue;
      try {
        g.addDirectedEdgeWithKey(e.id, e.source, e.target, {
          size: EDGE_DEFAULT_SIZE,
          color: edgeColorForDensity(1, maxDegree || 1),
          label: "",
        });
      } catch {
        /* duplicate key */
      }
    }

    if (g.order === 0) {
      loadGraph(g);
      onLoaded?.();
      return;
    }

    let communityIndex: Map<string, number> | null = null;
    const hasNativeCommunities =
      useNativeCommunities &&
      data.nodes.some((n) => n.community != null);

    if (hasNativeCommunities) {
      communityIndex = new Map<string, number>();
      for (const n of data.nodes) {
        if (n.community != null) {
          communityIndex.set(n.id, n.community);
        }
      }
    } else try {
      if (g.size > 0) {
        const partition = louvain(g, { resolution: 1.0 });
        // Build a stable index → color mapping so legend ordering is
        // deterministic across reloads.
        const seen = new Map<number | string, number>();
        communityIndex = new Map<string, number>();
        for (const [nodeId, c] of Object.entries(partition)) {
          let idx = seen.get(c);
          if (idx === undefined) {
            idx = seen.size;
            seen.set(c, idx);
          }
          communityIndex.set(nodeId, idx);
        }
        // Recolor each node + remember its community index for later use.
        g.forEachNode((id) => {
          const cIdx = communityIndex!.get(id) ?? 0;
          g.setNodeAttribute(id, "color", communityColor(cIdx));
          g.setNodeAttribute(id, "community", cIdx);
        });
      }
    } catch {
      /* Louvain occasionally fails on disconnected micro-graphs */
    }

    if (communityIndex && hasNativeCommunities) {
      g.forEachNode((id, attrs) => {
        const cIdx = attrs.community;
        if (typeof cIdx === "number") {
          g.setNodeAttribute(id, "color", communityColor(cIdx));
        }
      });
    } else if (!hasNativeCommunities) {
      // Louvain block above already recolored when successful
    }

    // ---- Density-aware edge alpha ----
    // Knowledge graphs concentrate edges around hubs. If we paint every
    // edge at the same alpha, the hub neighborhood becomes a solid mat
    // and the periphery looks bare. Scale alpha by the min degree of the
    // edge's endpoints: edges between two periphery nodes stay visible,
    // edges between two hubs fade so they don't smother the cluster.
    g.forEachEdge((edgeId, _attrs, source, target) => {
      const ds = degree.get(source) ?? 1;
      const dt = degree.get(target) ?? 1;
      const minD = Math.min(ds, dt);
      g.setEdgeAttribute(edgeId, "color", edgeColorForDensity(minD, maxDegree));
    });

    applyCurvedEdgeRendering(g);

    // ---- Hub-only labels ----
    // Showing 200+ labels at default zoom is unreadable. Reveal only the
    // top hubs (by degree) at base zoom; the rest become visible as the
    // user zooms or hovers. The threshold scales with graph size.
    const TOP_LABEL_COUNT = Math.max(12, Math.min(40, Math.round(g.order * 0.12)));
    const sortedByDegree = Array.from(degree.entries()).sort(
      (a, b) => b[1] - a[1],
    );
    const hubIds = new Set(
      sortedByDegree.slice(0, TOP_LABEL_COUNT).map(([id]) => id),
    );
    g.forEachNode((id, attrs) => {
      if (!hubIds.has(id)) {
        // Keep the label in the data (so hover + zoom can still surface
        // it) but blank the rendered label.
        g.setNodeAttribute(id, "labelHidden", true);
        g.setNodeAttribute(id, "fullLabel", attrs.label);
        g.setNodeAttribute(id, "label", "");
      } else {
        g.setNodeAttribute(id, "labelHidden", false);
        g.setNodeAttribute(id, "fullLabel", attrs.label);
      }
    });

    // ---- Initial positions ----
    // Seed nodes onto concentric rings *per community*. This makes the
    // very first frame look organized and gives ForceAtlas2 a much
    // friendlier starting condition than a single circle of 240 dots.
    if (communityIndex) {
      const byCommunity = new Map<number, string[]>();
      Array.from(communityIndex.entries()).forEach(([id, c]) => {
        if (!byCommunity.has(c)) byCommunity.set(c, []);
        byCommunity.get(c)!.push(id);
      });
      const communityCount = byCommunity.size;
      let cIdx = 0;
      Array.from(byCommunity.values()).forEach((members) => {
        const angle0 = (2 * Math.PI * cIdx) / Math.max(1, communityCount);
        const cx = Math.cos(angle0) * 350;
        const cy = Math.sin(angle0) * 350;
        members.forEach((id, i) => {
          const a = (2 * Math.PI * i) / Math.max(1, members.length);
          const r = 30 + members.length * 0.8;
          g.setNodeAttribute(id, "x", cx + Math.cos(a) * r + 0.02);
          g.setNodeAttribute(id, "y", cy + Math.sin(a) * r + 0.02);
        });
        cIdx += 1;
      });
    } else {
      let i = 0;
      g.forEachNode((id) => {
        const angle = (2 * Math.PI * i) / Math.max(1, g.order);
        g.setNodeAttribute(id, "x", Math.cos(angle) * 200 + 0.02);
        g.setNodeAttribute(id, "y", Math.sin(angle) * 200 + 0.02);
        i += 1;
      });
    }

    // ---- ForceAtlas2 settings ----
    // Use the library's ``inferSettings(graph)`` rather than hand-rolled
    // numbers. Empirically the previous combo (``barnesHutOptimize: true``
    // + ``linLogMode: true``) was collapsing the graph onto a thin
    // horizontal band — graphology-layout-forceatlas2's docs explicitly
    // warn that BarnesHut approximation interacts badly with linLog mode,
    // and ``inferSettings`` correctly disables BarnesHut for graphs
    // under 2 000 nodes while turning on ``strongGravityMode`` so
    // disconnected components stay bounded on the canvas.
    //
    // ``adjustSizes`` is the one aesthetic add-on we keep: it makes FA2
    // respect each node's rendered radius for collision avoidance so the
    // big hub nodes don't overlap their neighbours.
    const fa2Settings = {
      ...forceAtlas2.inferSettings(g),
      adjustSizes: true,
    };

    if (reducedMotion) {
      forceAtlas2.assign(g, {
        iterations: Math.min(180, 60 + g.order * 2),
        settings: fa2Settings,
      });
      normalizeGraphCoordinates(g);
      loadGraph(g);
      onLoaded?.();
      return;
    }

    let cancelled = false;
    let layout: { start: () => void; stop: () => void; kill: () => void } | null = null;

    void (async () => {
      try {
        const { default: FA2Layout } = await import("graphology-layout-forceatlas2/worker");
        if (cancelled) return;
        layout = new FA2Layout(g, { settings: fa2Settings });
        layout.start();
        // Heavier graphs need more wall-clock to relax. Cap at 8s so we
        // never hang the UI on outsized payloads.
        const ms = Math.min(8_000, 1_200 + Math.min(g.order, 3000) * 2.2);
        await new Promise<void>((resolve) => {
          window.setTimeout(() => resolve(), ms);
        });
        if (cancelled) {
          layout.stop();
          layout.kill();
          layout = null;
          return;
        }
        layout.stop();
        layout.kill();
        layout = null;
      } catch {
        forceAtlas2.assign(g, {
          iterations: Math.min(180, 60 + g.order * 2),
          settings: fa2Settings,
        });
      }
      if (!cancelled) {
        normalizeGraphCoordinates(g);
        loadGraph(g);
        onLoaded?.();
      }
    })();

    return () => {
      cancelled = true;
      layout?.stop();
      layout?.kill();
    };
  }, [data, loadGraph, reducedMotion, useNativeCommunities, onLoaded]);

  const registerEvents = useRegisterEvents();
  useEffect(() => {
    registerEvents({
      clickNode: (event: { node: string }) => {
        onSelectNode(event.node);
      },
      clickStage: () => {
        onSelectNode(null);
      },
    });
    return () => {
      registerEvents({});
    };
  }, [registerEvents, onSelectNode]);

  return null;
}

export function GraphCanvas({
  workspaceId,
  filters,
  graphBackend = "graphiti",
  graphragIndexId,
  communityId,
  onSelectNode,
  fullHeight = false,
  liveIngestion = false,
  onLivePatch,
}: {
  workspaceId: string;
  fullHeight?: boolean;
  filters: Record<string, string | undefined>;
  graphBackend?: "graphiti" | "graphrag";
  graphragIndexId?: string | null;
  communityId?: number | null;
  onSelectNode: (id: string | null) => void;
  liveIngestion?: boolean;
  onLivePatch?: () => void;
}) {
  const [data, setData] = useState<GraphPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reducedMotion, setReducedMotion] = useState(false);
  // Monotonic counter that bumps once the positioned graph has actually
  // been handed to Sigma. Camera fitting before that point races FA2 and
  // can reset against an empty/old graph.
  const [loadEpoch, setLoadEpoch] = useState(0);
  const handleGraphLoaded = useCallback(() => {
    setLoadEpoch((n) => n + 1);
  }, []);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const fn = () => setReducedMotion(mq.matches);
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);

  // D2 — split filters into "heavy" (drive the /graph query and require a
  // refetch + relayout) and "chip" (entity_types, edge_types, tag — applied
  // client-side as Sigma `hidden` attributes). Chip changes therefore
  // toggle visibility instantly without re-running ForceAtlas2.
  const qs = useMemo(() => {
    const p = new URLSearchParams();
    if (graphBackend === "graphrag") {
      p.set("backend", "graphrag");
      if (graphragIndexId) p.set("graphrag_index_id", graphragIndexId);
      if (filters.agent_id) p.set("agent_id", filters.agent_id);
      if (filters.collection_id) p.set("collection_id", filters.collection_id);
      if (communityId != null) p.set("community_id", String(communityId));
      if (filters.node_limit) p.set("node_limit", filters.node_limit);
      return p.toString();
    }
    p.set("view", filters.view ?? "overview");
    if (filters.document_id) p.set("document_id", filters.document_id);
    if (filters.agent_id) p.set("agent_id", filters.agent_id);
    if (filters.collection_id) p.set("collection_id", filters.collection_id);
    if (filters.valid_at) p.set("valid_at", filters.valid_at);
    if (filters.node_limit) p.set("node_limit", filters.node_limit);
    if (filters.depth) p.set("depth", filters.depth);
    const seeds = (filters.seed_entity_ids ?? "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    seeds.forEach((s) => p.append("seed_entity_ids", s));
    return p.toString();
  }, [filters, graphBackend, graphragIndexId, communityId]);

  const chipFilters = useMemo(
    () => ({
      entity_types: (filters.entity_types ?? "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      edge_types: (filters.edge_types ?? "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      tag: (filters.tag ?? "").trim(),
    }),
    [filters.entity_types, filters.edge_types, filters.tag],
  );

  const load = useCallback(async () => {
    setError(null);
    setData(null);
    try {
      const res = await fetchWithTimeout(
        `/api/v1/workspaces/${workspaceId}/graph?${qs}`,
        { cache: "no-store", timeoutMs: 90_000 },
      );
      const body = await readJsonResponse<GraphPayload & { error?: { message?: string } }>(res);
      if (!res.ok) {
        setError(readApiErrorMessage(body, "Failed to load graph"));
        setData(null);
        return;
      }
      setData({
        nodes: (body.nodes ?? []).map((n) => ({
          id: n.id,
          name: n.name,
          type: n.type ?? "entity",
          summary: n.summary ?? "",
          properties: n.properties ?? {},
          aliases: n.aliases ?? [],
          is_user_edited: n.is_user_edited ?? false,
          community: (n as GraphNode).community,
        })),
        edges: body.edges ?? [],
        truncated: Boolean(body.truncated),
      });
      // ``loadEpoch`` is bumped from the GraphLoader's ``onLoaded``
      // callback once FA2 finishes and Sigma has the positioned graph —
      // bumping here would fire the camera-reset too early (before FA2
      // even started) and cluster the graph at the top edge again.
    } catch (e) {
      setError(fetchTimeoutMessage(e));
      setData(null);
    }
  }, [workspaceId, qs]);

  useEffect(() => {
    void load();
  }, [load]);

  const { ref: canvasFrameRef, size: canvasSize } = useMeasuredCanvasFrame();
  // Only graph-load completion should trigger the "fit after data" path.
  // Container size changes are handled by CameraFitAndResize's internal
  // ResizeObserver. Including canvasSize here caused every measured-size
  // update to re-run the camera effect, which amplified the resize loop.
  const cameraEpoch = String(loadEpoch);

  if (error) {
    return (
      <div className="flex flex-col gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-caption text-destructive">
        <p>{error}</p>
        <button
          type="button"
          className="self-start rounded border border-input px-2 py-1 text-foreground hover:bg-card"
          onClick={() => void load()}
        >
          Retry
        </button>
      </div>
    );
  }
  if (!data) {
    return <p className="text-caption text-muted-foreground">Loading graph…</p>;
  }
  const showEmptyHint = data.nodes.length === 0 && !liveIngestion;
  if (showEmptyHint) {
    const agentHint = filters.agent_id
      ? "No entities for this agent with the current filters. Try clearing entity-type chips or re-import the conversation."
      : filters.collection_id
        ? "No entities for this collection with the current filters. Try clearing entity-type chips or wait for extract to finish."
      : graphBackend === "graphrag"
        ? "No GraphRAG entities yet. Build an index above, or pick a ready index."
        : "No entities in this workspace yet.";
    return <p className="text-caption text-muted-foreground">{agentHint}</p>;
  }

  const canvasData =
    data.nodes.length === 0 && liveIngestion ? EMPTY_LIVE_CANVAS : data;

  return (
    <div
      className={cn(
        "flex flex-1 flex-col gap-2",
        fullHeight ? "h-full min-h-0" : "min-h-[320px]",
      )}
    >
      {liveIngestion && data.nodes.length === 0 ? (
        <p className="text-caption text-caution/90">
          Live graph — entities will appear here as they are extracted…
        </p>
      ) : null}
      {data.truncated ? (
        <p className="text-caption text-amber-200/90">
          Graph truncated — add filters or lower scope (see node limit in URL).
        </p>
      ) : null}
      <div
        ref={canvasFrameRef}
        className={cn(
          "relative flex-1 overflow-hidden rounded-md border border-border bg-[#0b1220]",
          fullHeight ? "min-h-0" : "min-h-[420px]",
        )}
        style={{
          backgroundImage: GRAPH_CANVAS_BG,
          backgroundSize: GRAPH_CANVAS_BG_SIZE,
        }}
      >
        {canvasSize ? (
          <SigmaContainer
            style={{
              // Explicit pixel dimensions, measured from the flex frame,
              // but absolutely positioned so the child cannot affect the
              // parent frame's next measurement. The previous in-flow
              // measured-size version created a feedback loop:
              // measure frame -> set child height -> frame grows -> measure
              // larger -> repeat.
              position: "absolute",
              inset: 0,
              height: `${canvasSize.height}px`,
              width: `${canvasSize.width}px`,
              background: "#0b1220",
            }}
            settings={{
              renderLabels: true,
              labelRenderedSizeThreshold: 6,
              labelDensity: 0.55,
              labelColor: { color: "#f1f5f9" },
              labelFont: "Plus Jakarta Sans, system-ui, sans-serif",
              labelSize: 13,
              labelWeight: "600",
              defaultEdgeColor: "rgba(192, 192, 192, 0.35)",
              defaultEdgeType: "curved",
              defaultNodeType: "border",
              edgeProgramClasses: {
                curved: EdgeCurveProgram,
              },
              nodeProgramClasses: {
                border: NodeBorderProgram,
              },
              zIndex: true,
              allowInvalidContainer: true,
            }}
          >
            <GraphLoader
              data={canvasData}
              reducedMotion={reducedMotion}
              useNativeCommunities={graphBackend === "graphrag"}
              onSelectNode={onSelectNode}
              onLoaded={handleGraphLoaded}
            />
            <LiveGraphPatcher
              enabled={liveIngestion}
              reducedMotion={reducedMotion}
              onPatch={onLivePatch}
            />
            <ChipFilterApplier data={canvasData} chipFilters={chipFilters} />
            <GraphInteractionLayer nodes={canvasData.nodes} edges={canvasData.edges} />
            <CameraFitAndResize epoch={cameraEpoch} />
            <ZoomControls />
          </SigmaContainer>
        ) : (
          <div className="flex h-full min-h-[420px] items-center justify-center text-caption text-muted-foreground">
            Preparing graph canvas…
          </div>
        )}
        {canvasData.nodes.length > 0 ? (
          <GraphLegend data={canvasData} useNativeCommunities={graphBackend === "graphrag"} />
        ) : null}
      </div>
    </div>
  );
}
