"use client";

import { useCallback, useEffect, useState } from "react";

import { cn } from "@/lib/utils";

export type GraphragCommunityRow = {
  community: number;
  level?: number;
  title?: string;
  size?: number;
  entity_ids?: string[];
  report_title?: string | null;
  report_excerpt?: string | null;
  report_rank?: number | null;
};

export function GraphragCommunitySidebar({
  workspaceId,
  graphragIndexId,
  agentId,
  selectedCommunityId,
  onSelectCommunity,
}: {
  workspaceId: string;
  graphragIndexId?: string | null;
  agentId?: string | null;
  selectedCommunityId: number | null;
  onSelectCommunity: (communityId: number | null) => void;
}) {
  const [items, setItems] = useState<GraphragCommunityRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const p = new URLSearchParams();
      if (graphragIndexId) p.set("graphrag_index_id", graphragIndexId);
      if (agentId) p.set("agent_id", agentId);
      const qs = p.toString();
      const res = await fetch(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/graphrag/communities${qs ? `?${qs}` : ""}`,
        { cache: "no-store" },
      );
      const body = (await res.json()) as { items?: GraphragCommunityRow[]; error?: { message?: string } };
      if (!res.ok) {
        setError(body.error?.message ?? "Failed to load communities");
        setItems([]);
        return;
      }
      setItems(body.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load communities");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [workspaceId, graphragIndexId, agentId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <aside
      aria-label="GraphRAG communities"
      className="flex max-h-[min(50vh,420px)] w-full shrink-0 flex-col rounded-md border border-border bg-card/80 xl:max-h-none xl:w-[min(100%,16rem)]"
    >
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <p className="text-caption font-semibold uppercase tracking-wider text-muted-foreground">
          Communities
        </p>
        {selectedCommunityId != null ? (
          <button
            type="button"
            className="text-caption text-primary hover:underline"
            onClick={() => onSelectCommunity(null)}
          >
            Clear
          </button>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {loading ? (
          <p className="px-1 text-caption text-muted-foreground">Loading…</p>
        ) : error ? (
          <p className="px-1 text-caption text-destructive">{error}</p>
        ) : items.length === 0 ? (
          <p className="px-1 text-caption text-muted-foreground">No communities in this index.</p>
        ) : (
          <ul className="space-y-1">
            {items.map((c) => {
              const active = selectedCommunityId === c.community;
              const label = c.report_title || c.title || `Community ${c.community}`;
              return (
                <li key={c.community}>
                  <button
                    type="button"
                    onClick={() => onSelectCommunity(active ? null : c.community)}
                    className={cn(
                      "w-full rounded-md px-2 py-1.5 text-left text-caption transition",
                      active
                        ? "bg-secondary text-foreground"
                        : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                    )}
                  >
                    <span className="line-clamp-2 font-medium">{label}</span>
                    <span className="mt-0.5 block text-[10px] text-muted-foreground">
                      {c.size ?? c.entity_ids?.length ?? 0} entities
                      {c.level != null ? ` · L${c.level}` : ""}
                    </span>
                    {c.report_excerpt ? (
                      <span className="mt-1 line-clamp-2 block text-[10px] text-muted-foreground/90">
                        {c.report_excerpt}
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
