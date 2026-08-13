import {
  DEFAULT_EDGE_CURVATURE,
  indexParallelEdgesIndex,
} from "@sigma/edge-curve";
import type Graph from "graphology";

/** MiroFish-inspired palette — distinct hues on dark canvas. */
export const TYPE_COLORS: Record<string, string> = {
  Person: "#fbbf24",
  Organization: "#38bdf8",
  Concept: "#34d399",
  Location: "#a78bfa",
  Work: "#f472b6",
  Event: "#22d3ee",
  Document: "#fb7185",
  Equipment: "#fb923c",
  Process: "#84cc16",
  Standard: "#e879f9",
  Material: "#60a5fa",
  Component: "#818cf8",
};

export const COMMUNITY_PALETTE = [
  "#38bdf8",
  "#fbbf24",
  "#a78bfa",
  "#34d399",
  "#f472b6",
  "#fb923c",
  "#22d3ee",
  "#e879f9",
  "#84cc16",
  "#fb7185",
  "#60a5fa",
  "#818cf8",
];

export function communityColor(idx: number): string {
  return COMMUNITY_PALETTE[idx % COMMUNITY_PALETTE.length];
}

export function colorForType(t: string): string {
  if (TYPE_COLORS[t]) return TYPE_COLORS[t];
  let h = 0;
  for (let i = 0; i < t.length; i += 1) {
    h = (h * 31 + t.charCodeAt(i)) | 0;
  }
  return COMMUNITY_PALETTE[Math.abs(h) % COMMUNITY_PALETTE.length];
}

/** Readable nodes — between the old oversized hubs and the first MiroFish pass. */
export function nodeSizeForDegree(degree: number, maxDegree: number): number {
  const base = 2.6;
  const norm = maxDegree > 0 ? Math.sqrt(degree) / Math.sqrt(maxDegree) : 0;
  return base + norm * 8;
}

export const LIVE_NODE_SIZE = 3.4;
export const EDGE_DEFAULT_SIZE = 0.38;
export const EDGE_LIVE_SIZE = 0.42;
export const NODE_BORDER_COLOR = "#f1f5f9";
export const NODE_BORDER_SIZE = 0.12;

export function edgeColorForDensity(minDegree: number, maxDegree: number): string {
  const norm = maxDegree > 0 ? Math.min(1, minDegree / Math.max(1, maxDegree / 2)) : 0;
  const alpha = 0.42 - norm * 0.28;
  return `rgba(192, 192, 192, ${alpha.toFixed(2)})`;
}

function curvatureForParallelIndex(index: number, maxIndex: number): number {
  if (maxIndex <= 0) return DEFAULT_EDGE_CURVATURE * 0.3;
  if (index < 0) return -curvatureForParallelIndex(-index, maxIndex);
  const amplitude = 3.5;
  const maxCurvature =
    amplitude * (1 - Math.exp(-maxIndex / amplitude)) * DEFAULT_EDGE_CURVATURE;
  return (maxCurvature * index) / maxIndex;
}

/** Quadratic Bézier edges — mirrors MiroFish curved link paths. */
export function applyCurvedEdgeRendering(g: Graph): void {
  if (g.size === 0) return;

  indexParallelEdgesIndex(g, {
    edgeIndexAttribute: "parallelIndex",
    edgeMinIndexAttribute: "parallelMinIndex",
    edgeMaxIndexAttribute: "parallelMaxIndex",
  });

  g.forEachEdge((edge, attrs) => {
    const a = attrs as {
      parallelIndex?: number | null;
      parallelMinIndex?: number | null;
      parallelMaxIndex?: number;
    };

    if (typeof a.parallelMinIndex === "number" && typeof a.parallelMaxIndex === "number") {
      const idx = a.parallelIndex ?? 0;
      g.mergeEdgeAttributes(edge, {
        type: idx !== 0 ? "curved" : "straight",
        curvature: curvatureForParallelIndex(idx, a.parallelMaxIndex),
      });
      return;
    }

    if (typeof a.parallelIndex === "number" && typeof a.parallelMaxIndex === "number") {
      g.mergeEdgeAttributes(edge, {
        type: "curved",
        curvature: curvatureForParallelIndex(a.parallelIndex, a.parallelMaxIndex),
      });
      return;
    }

    g.mergeEdgeAttributes(edge, {
      type: "curved",
      curvature: DEFAULT_EDGE_CURVATURE * 0.28,
    });
  });
}

export const GRAPH_CANVAS_BG =
  "radial-gradient(circle, rgba(148, 163, 184, 0.14) 1px, transparent 1px)";

export const GRAPH_CANVAS_BG_SIZE = "24px 24px";
