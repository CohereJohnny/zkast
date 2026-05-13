"use client";

import "@react-sigma/core/lib/style.css";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  SigmaContainer,
  useLoadGraph,
  useRegisterEvents,
  useSigma,
} from "@react-sigma/core";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import louvain from "graphology-communities-louvain";

export type GraphNode = {
  id: string;
  type: string;
  name: string;
  summary: string;
  properties: Record<string, unknown>;
  aliases: string[];
  is_user_edited: boolean;
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

// Vibrant, dark-mode-friendly palette. Each type gets a distinct hue so a
// large graph reads at a glance instead of as a green mush. Tailwind 400/500
// stops were chosen for ~70% saturation and ~4.5:1 contrast on the canvas
// background.
const TYPE_COLORS: Record<string, string> = {
  Person: "#fbbf24", // amber-400
  Organization: "#38bdf8", // sky-400
  Concept: "#34d399", // emerald-400
  Location: "#a78bfa", // violet-400
  Work: "#f472b6", // pink-400
  Event: "#22d3ee", // cyan-400
  Document: "#fb7185", // rose-400
  Equipment: "#fb923c", // orange-400
  Process: "#84cc16", // lime-500
  Standard: "#e879f9", // fuchsia-400
  Material: "#60a5fa", // blue-400
  Component: "#818cf8", // indigo-400
};

// 12 visually distinct hues used for community-based coloring AND for
// fallback type coloring. Picked from Tailwind 400/500 with care that no
// two adjacent colors are too close in hue for colorblind users.
const COMMUNITY_PALETTE = [
  "#38bdf8", // sky-400
  "#fbbf24", // amber-400
  "#a78bfa", // violet-400
  "#34d399", // emerald-400
  "#f472b6", // pink-400
  "#fb923c", // orange-400
  "#22d3ee", // cyan-400
  "#e879f9", // fuchsia-400
  "#84cc16", // lime-500
  "#fb7185", // rose-400
  "#60a5fa", // blue-400
  "#818cf8", // indigo-400
];

function communityColor(idx: number): string {
  return COMMUNITY_PALETTE[idx % COMMUNITY_PALETTE.length];
}

function colorForType(t: string): string {
  if (TYPE_COLORS[t]) return TYPE_COLORS[t];
  let h = 0;
  for (let i = 0; i < t.length; i += 1) {
    h = (h * 31 + t.charCodeAt(i)) | 0;
  }
  return COMMUNITY_PALETTE[Math.abs(h) % COMMUNITY_PALETTE.length];
}

// Degree-based sizing so high-connectivity hubs are visually prominent and
// leaf nodes shrink out of the way. sqrt() compresses the long tail so a
// degree-100 hub doesn't dwarf a degree-1 leaf by 100×. Raised the ceiling
// vs. the first pass so hubs are clearly readable in 200+ node graphs.
function nodeSizeForDegree(degree: number, maxDegree: number): number {
  const base = 2.5;
  const norm = maxDegree > 0 ? Math.sqrt(degree) / Math.sqrt(maxDegree) : 0;
  return base + norm * 18; // range ~2.5–20 px
}

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
 * Wires hover emphasis: dim everything that isn't the hovered node or one
 * of its incident edges. Mirrors what MiroFish does on hover and what the
 * Graphiti reference UI does. Implemented via Sigma's node/edge reducers
 * so it's GPU-cheap.
 */
function HoverEmphasis() {
  const sigma = useSigma();
  const [hovered, setHovered] = useState<string | null>(null);

  useEffect(() => {
    // Pre-compute the neighbor set once per hover change so the per-node
    // reducer is O(1) instead of O(degree) on every render frame.
    let neighborSet: Set<string> | null = null;
    if (hovered) {
      const g = sigma.getGraph();
      if (g.hasNode(hovered)) {
        neighborSet = new Set(g.neighbors(hovered));
        neighborSet.add(hovered);
      }
    }

    sigma.setSetting("nodeReducer", (node, attrs) => {
      if (!neighborSet) return attrs;
      if (neighborSet.has(node)) {
        // Hub-only labels are blanked at base zoom; on hover, surface the
        // full label from the ``fullLabel`` shadow attribute so the user
        // can read peripheral nodes once they're investigated.
        const restoredLabel = attrs.fullLabel || attrs.label;
        return {
          ...attrs,
          label: restoredLabel,
          zIndex: 2,
          forceLabel: true,
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
      if (!hovered) return attrs;
      const g = sigma.getGraph();
      const [source, target] = g.extremities(edge);
      const incident = source === hovered || target === hovered;
      if (incident) {
        return {
          ...attrs,
          color: "rgba(20, 184, 166, 0.85)", // accent teal
          size: Math.max(attrs.size ?? 1, 1.2),
          zIndex: 2,
        };
      }
      return {
        ...attrs,
        color: "rgba(148, 163, 184, 0.08)",
        hidden: false,
        zIndex: 0,
      };
    });

    sigma.refresh();
  }, [sigma, hovered]);

  const registerEvents = useRegisterEvents();
  useEffect(() => {
    registerEvents({
      enterNode: (event: { node: string }) => setHovered(event.node),
      leaveNode: () => setHovered(null),
    });
  }, [registerEvents]);

  return null;
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
function GraphLegend({ data }: { data: GraphPayload }) {
  const { mode, entries } = useMemo(() => {
    if (data.nodes.length === 0) {
      return { mode: "types" as const, entries: [] };
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

    // For each community, pick the highest-degree node as its label so
    // the legend reads "Reactor Coolant System" rather than "Cluster 3".
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
  }, [data]);

  if (entries.length === 0) return null;

  return (
    <div
      aria-label={mode === "types" ? "Entity type legend" : "Cluster legend"}
      className="pointer-events-none absolute bottom-3 left-3 z-10 max-w-[18rem] rounded-md border border-border-subtle bg-surface-overlay px-2.5 py-2 backdrop-blur"
    >
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted">
        {mode === "types" ? "Entity types" : "Clusters · top node shown"}
      </p>
      <ul className="flex flex-col gap-1">
        {entries.map((e) => (
          <li
            key={e.key}
            className="flex items-center gap-2 text-[11px] text-secondary"
          >
            <span
              aria-hidden="true"
              className="h-2 w-2 flex-shrink-0 rounded-full"
              style={{ backgroundColor: e.color }}
            />
            <span className="truncate">{e.label}</span>
            <span className="ml-auto text-muted">{e.count}</span>
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
      className="flex h-7 w-7 cursor-pointer items-center justify-center rounded border border-border-strong bg-surface-overlay text-secondary backdrop-blur transition-colors duration-150 hover:bg-surface-raised focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
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

function GraphLoader({
  data,
  reducedMotion,
  onSelectNode,
}: {
  data: GraphPayload;
  reducedMotion: boolean;
  onSelectNode: (id: string | null) => void;
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
      g.addNode(n.id, {
        label: n.name,
        size: nodeSizeForDegree(degree.get(n.id) ?? 0, maxDegree),
        // Provisional color — Louvain overwrites below once edges are in.
        color: colorForType(n.type),
        borderColor: "#020617",
        borderSize: 0.5,
        // Shadow attributes consumed by GraphLegend / HoverEmphasis.
        entityType: n.type,
      });
    }

    for (const e of data.edges) {
      if (!g.hasNode(e.source) || !g.hasNode(e.target)) continue;
      if (g.hasEdge(e.id)) continue;
      try {
        g.addDirectedEdgeWithKey(e.id, e.source, e.target, {
          size: 0.6,
          color: "rgba(148, 163, 184, 0.18)",
          label: "",
        });
      } catch {
        /* duplicate key */
      }
    }

    if (g.order === 0) {
      loadGraph(g);
      return;
    }

    // ---- Community detection (Louvain) ----
    // When all entity types collapse to a single label ("Concept" in
    // current Graphiti), color-by-type produces a monochromatic blob.
    // Louvain partitions the graph by topology and reveals the actual
    // semantic clusters, which is the standard knowledge-graph rendering
    // trick (used in MiroFish, Obsidian Graph, etc.).
    let communityIndex: Map<string, number> | null = null;
    try {
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
      /* Louvain occasionally fails on disconnected micro-graphs;
       * fall back silently to the type-based coloring already in place. */
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
      // alpha is high (0.55) for periphery-periphery edges and decays to
      // 0.12 in the densest cluster centers.
      const norm = maxDegree > 0 ? Math.min(1, minD / Math.max(1, maxDegree / 2)) : 0;
      const alpha = 0.55 - norm * 0.43;
      g.setEdgeAttribute(
        edgeId,
        "color",
        `rgba(148, 163, 184, ${alpha.toFixed(2)})`,
      );
    });

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
    // linLogMode + low gravity + high scalingRatio is the canonical
    // recipe for spreading dense knowledge graphs out without losing
    // their community structure. strongGravityMode stays off so isolated
    // subgraphs can drift to the periphery instead of being smashed
    // into the hub.
    const fa2Settings = {
      barnesHutOptimize: true,
      barnesHutTheta: 0.6,
      linLogMode: true,
      adjustSizes: true, // respect node size for collision avoidance
      gravity: 0.08,
      scalingRatio: 20,
      slowDown: 6,
      edgeWeightInfluence: 0,
      strongGravityMode: false,
    };

    if (reducedMotion) {
      forceAtlas2.assign(g, {
        iterations: Math.min(180, 60 + g.order * 2),
        settings: fa2Settings,
      });
      loadGraph(g);
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
      if (!cancelled) loadGraph(g);
    })();

    return () => {
      cancelled = true;
      layout?.stop();
      layout?.kill();
    };
  }, [data, loadGraph, reducedMotion]);

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
  onSelectNode,
}: {
  workspaceId: string;
  filters: Record<string, string | undefined>;
  onSelectNode: (id: string | null) => void;
}) {
  const [data, setData] = useState<GraphPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reducedMotion, setReducedMotion] = useState(false);

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
    p.set("view", filters.view ?? "overview");
    if (filters.document_id) p.set("document_id", filters.document_id);
    if (filters.valid_at) p.set("valid_at", filters.valid_at);
    if (filters.node_limit) p.set("node_limit", filters.node_limit);
    if (filters.depth) p.set("depth", filters.depth);
    const seeds = (filters.seed_entity_ids ?? "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    seeds.forEach((s) => p.append("seed_entity_ids", s));
    return p.toString();
  }, [filters]);

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
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/graph?${qs}`, { cache: "no-store" });
      const body = (await res.json()) as GraphPayload & { error?: { message?: string } };
      if (!res.ok) {
        setError(body.error?.message ?? "Failed to load graph");
        setData(null);
        return;
      }
      setData({
        nodes: body.nodes ?? [],
        edges: body.edges ?? [],
        truncated: Boolean(body.truncated),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load graph");
      setData(null);
    }
  }, [workspaceId, qs]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return <p className="text-caption text-red-300">{error}</p>;
  }
  if (!data) {
    return <p className="text-caption text-muted">Loading graph…</p>;
  }
  if (data.nodes.length === 0) {
    return <p className="text-caption text-muted">No entities in this workspace yet.</p>;
  }

  return (
    <div className="flex min-h-[320px] flex-1 flex-col gap-2">
      {data.truncated ? (
        <p className="text-caption text-amber-200/90">
          Graph truncated — add filters or lower scope (see node limit in URL).
        </p>
      ) : null}
      <div className="relative min-h-[420px] flex-1 overflow-hidden rounded-md border border-border-subtle bg-canvas">
        <SigmaContainer
          style={{
            // Fill the parent's flex-allocated height instead of capping at
            // 540px — the previous fixed ceiling left a large empty band
            // below the canvas on tall viewports. ``min-h-[420px]`` on the
            // wrapper ensures we never collapse below a useful size.
            height: "100%",
            width: "100%",
            // Subtle radial gradient gives the canvas depth so the graph
            // floats over the surface rather than sitting flat on it.
            background:
              "radial-gradient(ellipse at center, #0b1224 0%, #020617 70%)",
          }}
          settings={{
            renderLabels: true,
            // Only show a node's label when its rendered size is at least
            // this many pixels. Cuts label clutter dramatically on 200+
            // node graphs without losing top-degree hubs.
            labelRenderedSizeThreshold: 6,
            labelDensity: 0.7,
            labelColor: { color: "#e2e8f0" },
            labelFont: "Plus Jakarta Sans, sans-serif",
            labelSize: 12,
            labelWeight: "500",
            defaultEdgeColor: "rgba(148, 163, 184, 0.35)",
            zIndex: true,
            allowInvalidContainer: true,
          }}
        >
          <GraphLoader data={data} reducedMotion={reducedMotion} onSelectNode={onSelectNode} />
          <ChipFilterApplier data={data} chipFilters={chipFilters} />
          <HoverEmphasis />
          <ZoomControls />
        </SigmaContainer>
        <GraphLegend data={data} />
      </div>
    </div>
  );
}
