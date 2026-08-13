"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { readApiErrorMessage } from "@/lib/api-error-message";
import { fetchWithTimeout, readJsonResponse } from "@/lib/fetch-with-timeout";
import { cn } from "@/lib/utils";

type EntityDetail = {
  id: string;
  name: string;
  type: string;
  description?: string;
  community?: number | null;
  community_report?: {
    community?: number;
    title?: string | null;
    rank?: number | null;
    excerpt?: string;
  } | null;
};

export function GraphragEntityPanel({
  workspaceId,
  entityId,
  graphragIndexId,
  agentId,
  onClose,
  onSelectCommunity,
  onGraphitiMatch,
}: {
  workspaceId: string;
  entityId: string;
  graphragIndexId?: string | null;
  agentId?: string | null;
  onClose: () => void;
  onSelectCommunity?: (communityId: number) => void;
  onGraphitiMatch?: (graphitiEntityId: string) => void;
}) {
  const [entity, setEntity] = useState<EntityDetail | null>(null);
  const [graphitiMatchId, setGraphitiMatchId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const p = new URLSearchParams();
        if (graphragIndexId) p.set("graphrag_index_id", graphragIndexId);
        if (agentId) p.set("agent_id", agentId);
        const qs = p.toString();
        const res = await fetchWithTimeout(
          `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/graphrag/entities/${encodeURIComponent(entityId)}${qs ? `?${qs}` : ""}`,
          { cache: "no-store", timeoutMs: 30_000 },
        );
        const body = await readJsonResponse<{ entity?: EntityDetail }>(res);
        if (cancelled) return;
        if (!res.ok || !body.entity) {
          setError(
            readApiErrorMessage(
              body,
              res.ok ? "GraphRAG entity response was empty" : "Failed to load GraphRAG entity",
            ),
          );
          setEntity(null);
          return;
        }
        setEntity(body.entity);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load entity");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, entityId, graphragIndexId, agentId]);

  const lookupGraphitiMatch = useCallback(async () => {
    if (!entity?.name?.trim()) return;
    try {
      const q = encodeURIComponent(entity.name.trim().slice(0, 80));
      const scope = agentId ? `&agent_id=${encodeURIComponent(agentId)}` : "";
      const res = await fetch(
        `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/graph/entities/search-typeahead?q=${q}&limit=5${scope}`,
        { cache: "no-store" },
      );
      const body = (await res.json()) as { items?: { id: string; name: string }[] };
      if (!res.ok || !body.items?.length) {
        setGraphitiMatchId(null);
        return;
      }
      const normalized = entity.name.trim().toLowerCase();
      const exact = body.items.find((i) => i.name.trim().toLowerCase() === normalized);
      const match = exact ?? body.items[0];
      setGraphitiMatchId(match?.id ?? null);
    } catch {
      setGraphitiMatchId(null);
    }
  }, [entity, workspaceId, agentId]);

  useEffect(() => {
    void lookupGraphitiMatch();
  }, [lookupGraphitiMatch]);

  const report = entity?.community_report;

  return (
    <div className={cn("flex flex-col gap-2 text-caption")}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-p font-semibold text-foreground">{entity?.name ?? entityId}</p>
          {entity?.type ? <p className="text-muted-foreground">{entity.type}</p> : null}
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>

      {loading ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : error ? (
        <p className="text-destructive">{error}</p>
      ) : entity ? (
        <>
          {entity.description ? (
            <section>
              <p className="font-medium text-muted-foreground">Description</p>
              <p className="mt-1 text-foreground">{entity.description}</p>
            </section>
          ) : null}

          {entity.community != null ? (
            <section>
              <p className="font-medium text-muted-foreground">Community</p>
              <button
                type="button"
                className="mt-1 text-primary hover:underline"
                onClick={() => onSelectCommunity?.(entity.community!)}
              >
                {report?.title ?? `Community ${entity.community}`}
              </button>
            </section>
          ) : null}

          {report?.excerpt ? (
            <section>
              <p className="font-medium text-muted-foreground">Community report</p>
              <p className="mt-1 whitespace-pre-wrap text-foreground">{report.excerpt}</p>
            </section>
          ) : null}

          {graphitiMatchId ? (
            <section className="rounded-md border border-border bg-secondary/30 p-2">
              <p className="font-medium text-muted-foreground">Graphiti cross-link</p>
              <button
                type="button"
                className="mt-1 text-primary hover:underline"
                onClick={() => onGraphitiMatch?.(graphitiMatchId)}
              >
                See in Graphiti graph
              </button>
            </section>
          ) : null}

          <p className="text-[10px] text-muted-foreground">
            Read-only GraphRAG entity — no merge or PDF evidence in this mode.
          </p>
        </>
      ) : null}
    </div>
  );
}
