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

const TYPE_COLORS: Record<string, string> = {
  Person: "#7dd3fc",
  Organization: "#c4b5fd",
  Concept: "#86efac",
  Location: "#fcd34d",
  Work: "#f9a8d4",
};

function colorForType(t: string): string {
  return TYPE_COLORS[t] ?? "#94a3b8";
}

function nodeSizeForEntityType(t: string): number {
  switch (t) {
    case "Person":
      return 12;
    case "Organization":
      return 14;
    case "Concept":
      return 10;
    case "Location":
      return 11;
    case "Work":
      return 13;
    default:
      return 9;
  }
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
    // D2 — toggle `hidden` per node/edge instead of relayouting. Sigma
    // respects the attribute natively.
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
    for (const n of data.nodes) {
      g.addNode(n.id, {
        label: n.name,
        size: nodeSizeForEntityType(n.type),
        color: colorForType(n.type),
        borderColor: "#0f172a",
        borderSize: n.type === "Organization" || n.type === "Work" ? 2 : 0.5,
      });
    }
    for (const e of data.edges) {
      if (!g.hasNode(e.source) || !g.hasNode(e.target)) continue;
      if (!g.hasEdge(e.id)) {
        try {
          g.addDirectedEdgeWithKey(e.id, e.source, e.target, {
            size: 1.5,
            color: "#64748b",
            label: e.type,
          });
        } catch {
          /* duplicate key */
        }
      }
    }

    let i = 0;
    g.forEachNode((id) => {
      const angle = (2 * Math.PI * i) / Math.max(1, g.order);
      g.setNodeAttribute(id, "x", Math.cos(angle) * 200 + 0.02);
      g.setNodeAttribute(id, "y", Math.sin(angle) * 200 + 0.02);
      i += 1;
    });

    if (g.order === 0) {
      loadGraph(g);
      return;
    }

    if (reducedMotion) {
      loadGraph(g);
      return;
    }

    let cancelled = false;
    let layout: { start: () => void; stop: () => void; kill: () => void } | null = null;

    void (async () => {
      try {
        const { default: FA2Layout } = await import("graphology-layout-forceatlas2/worker");
        if (cancelled) return;
        layout = new FA2Layout(g, {
          settings: { barnesHutOptimize: g.order > 400, gravity: 0.88, scalingRatio: 8 },
        });
        layout.start();
        const ms = Math.min(3200, 550 + Math.min(g.order, 2500) * 1.5);
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
        forceAtlas2.assign(g, { iterations: Math.min(100, 35 + g.order * 2) });
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
      <div className="relative min-h-[280px] flex-1 rounded-md border border-border-subtle bg-canvas">
        <SigmaContainer
          style={{ height: "min(55vh, 480px)", width: "100%" }}
          settings={{
            renderLabels: true,
            labelDensity: 0.45,
            labelFont: "Plus Jakarta Sans, sans-serif",
          }}
        >
          <GraphLoader data={data} reducedMotion={reducedMotion} onSelectNode={onSelectNode} />
          <ChipFilterApplier data={data} chipFilters={chipFilters} />
        </SigmaContainer>
      </div>
    </div>
  );
}
