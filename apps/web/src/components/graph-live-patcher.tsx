"use client";

import { useCallback, useEffect, useRef } from "react";
import { useSigma } from "@react-sigma/core";

import {
  applyCurvedEdgeRendering,
  colorForType,
  EDGE_DEFAULT_SIZE,
  EDGE_LIVE_SIZE,
  LIVE_NODE_SIZE,
  NODE_BORDER_COLOR,
  NODE_BORDER_SIZE,
  edgeColorForDensity,
} from "@/lib/graph-visual-style";
import { type GraphLiveDelta, useGraphLiveDelta } from "@/lib/graph-live-delta";

function placementForNewNode(
  g: {
    order: number;
    forEachNode: (fn: (id: string, attrs: Record<string, unknown>) => void) => void;
  },
  index: number,
): { x: number; y: number } {
  if (g.order === 0) {
    const angle = (index / 8) * Math.PI * 2;
    return { x: Math.cos(angle) * 2, y: Math.sin(angle) * 2 };
  }
  let sx = 0;
  let sy = 0;
  let n = 0;
  g.forEachNode((_id, attrs) => {
    sx += (attrs.x as number) ?? 0;
    sy += (attrs.y as number) ?? 0;
    n += 1;
  });
  const cx = sx / n;
  const cy = sy / n;
  const spread = Math.min(3.5, 0.8 + Math.sqrt(g.order) * 0.12);
  const angle = Math.random() * Math.PI * 2;
  return { x: cx + Math.cos(angle) * spread, y: cy + Math.sin(angle) * spread };
}

function flashNode(
  sigma: ReturnType<typeof useSigma>,
  nodeId: string,
  reducedMotion: boolean,
) {
  const g = sigma.getGraph();
  if (!g.hasNode(nodeId)) return;
  const base = String(g.getNodeAttribute(nodeId, "color") ?? colorForType("Concept"));
  const baseSize = (g.getNodeAttribute(nodeId, "size") as number) ?? LIVE_NODE_SIZE;
  g.setNodeAttribute(nodeId, "color", "#f472b6");
  g.setNodeAttribute(nodeId, "size", baseSize * 1.45);
  g.setNodeAttribute(nodeId, "borderColor", "#fce7f3");
  g.setNodeAttribute(nodeId, "borderSize", NODE_BORDER_SIZE * 2);
  sigma.refresh();
  window.setTimeout(() => {
    if (!g.hasNode(nodeId)) return;
    g.setNodeAttribute(nodeId, "color", base);
    g.setNodeAttribute(nodeId, "size", baseSize);
    g.setNodeAttribute(nodeId, "borderColor", NODE_BORDER_COLOR);
    g.setNodeAttribute(nodeId, "borderSize", NODE_BORDER_SIZE);
    sigma.refresh();
  }, reducedMotion ? 320 : 750);
}

function flashEdge(
  sigma: ReturnType<typeof useSigma>,
  edgeId: string,
  reducedMotion: boolean,
) {
  const g = sigma.getGraph();
  if (!g.hasEdge(edgeId)) return;
  g.setEdgeAttribute(edgeId, "color", "rgba(244, 114, 182, 0.9)");
  g.setEdgeAttribute(edgeId, "size", EDGE_LIVE_SIZE * 2.2);
  sigma.refresh();
  window.setTimeout(() => {
    if (!g.hasEdge(edgeId)) return;
    g.setEdgeAttribute(edgeId, "color", edgeColorForDensity(1, 4));
    g.setEdgeAttribute(edgeId, "size", EDGE_DEFAULT_SIZE);
    sigma.refresh();
  }, reducedMotion ? 320 : 750);
}

export function LiveGraphPatcher({
  enabled,
  reducedMotion,
  onPatch,
}: {
  enabled: boolean;
  reducedMotion: boolean;
  onPatch?: () => void;
}) {
  const sigma = useSigma();
  const seenNodes = useRef(new Set<string>());
  const seenEdges = useRef(new Set<string>());
  const patchIndex = useRef(0);
  const lastCameraNudge = useRef(0);

  const applyDelta = useCallback(
    (delta: GraphLiveDelta) => {
      if (!enabled) return;
      const g = sigma.getGraph();
      let touched = false;

      for (const n of delta.nodes) {
        if (seenNodes.current.has(n.id)) continue;
        seenNodes.current.add(n.id);
        if (!g.hasNode(n.id)) {
          const pos = placementForNewNode(g, patchIndex.current++);
          g.addNode(n.id, {
            label: n.name,
            type: "border",
            x: pos.x,
            y: pos.y,
            size: LIVE_NODE_SIZE,
            color: colorForType(n.type),
            borderColor: NODE_BORDER_COLOR,
            borderSize: NODE_BORDER_SIZE,
            entityType: n.type,
          });
          flashNode(sigma, n.id, reducedMotion);
          touched = true;
        }
      }

      for (const e of delta.edges) {
        if (seenEdges.current.has(e.id)) continue;
        if (!g.hasNode(e.source) || !g.hasNode(e.target)) continue;
        seenEdges.current.add(e.id);
        if (!g.hasEdge(e.id)) {
          try {
            g.addDirectedEdgeWithKey(e.id, e.source, e.target, {
              size: EDGE_DEFAULT_SIZE,
              color: edgeColorForDensity(1, 4),
              label: "",
            });
            flashEdge(sigma, e.id, reducedMotion);
            touched = true;
          } catch {
            /* duplicate */
          }
        }
      }

      if (touched) {
        applyCurvedEdgeRendering(g);
        sigma.refresh();

        const now = Date.now();
        const shouldNudge =
          g.order === 1 ||
          (g.order > 0 && g.order % 12 === 0 && now - lastCameraNudge.current > 800);
        if (shouldNudge) {
          lastCameraNudge.current = now;
          try {
            sigma.getCamera().animatedReset({ duration: reducedMotion ? 0 : 280 });
          } catch {
            /* ignore */
          }
        }
        onPatch?.();
      }
    },
    [enabled, onPatch, reducedMotion, sigma],
  );

  useGraphLiveDelta(applyDelta);

  useEffect(() => {
    if (!enabled) {
      seenNodes.current.clear();
      seenEdges.current.clear();
      patchIndex.current = 0;
      lastCameraNudge.current = 0;
      return;
    }
    const g = sigma.getGraph();
    g.forEachNode((id) => seenNodes.current.add(id));
    g.forEachEdge((id) => seenEdges.current.add(id));
  }, [enabled, sigma]);

  return null;
}
