"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useToast } from "@/components/feedback-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type AgentRow = {
  id: string;
  display_name?: string | null;
  external_agent_id?: string | null;
  provider?: string | null;
};

type IndexRow = {
  id: string;
  agent_id?: string | null;
  status: string;
  stats?: Record<string, unknown> | null;
  failure_reason?: string | null;
  provider?: string | null;
  created_at?: string | null;
};

type Space = { key: string; agentId: string | null; label: string; kind: "workspace" | "channel" | "agent" };

function statusVariant(status: string): "success" | "caution" | "secondary" | "destructive" | "info" {
  if (status === "ready") return "success";
  if (status === "running" || status === "pending") return "caution";
  if (status === "failed") return "destructive";
  return "secondary";
}

export function GraphragPageClient({ workspaceId }: { workspaceId: string }) {
  const toast = useToast();
  const base = `/api/v1/workspaces/${encodeURIComponent(workspaceId)}`;

  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [indexes, setIndexes] = useState<IndexRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [maxDocs, setMaxDocs] = useState(200);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadIndexes = useCallback(async () => {
    try {
      const res = await fetch(`${base}/graphrag/indexes`, { cache: "no-store" });
      const body = (await res.json()) as { items?: IndexRow[] };
      if (res.ok) setIndexes(body.items ?? []);
    } catch {
      /* transient */
    }
  }, [base]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [aRes] = await Promise.all([
        fetch(`${base}/north/agents`, { cache: "no-store" }),
        loadIndexes(),
      ]);
      const aBody = (await aRes.json().catch(() => ({}))) as { items?: AgentRow[] };
      if (aRes.ok) setAgents(aBody.items ?? []);
    } finally {
      setLoading(false);
    }
  }, [base, loadIndexes]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  // Poll while any index is pending/running.
  const anyActive = useMemo(
    () => indexes.some((i) => i.status === "pending" || i.status === "running"),
    [indexes],
  );
  useEffect(() => {
    if (anyActive && !pollRef.current) {
      pollRef.current = setInterval(() => void loadIndexes(), 5000);
    } else if (!anyActive && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [anyActive, loadIndexes]);

  const spaces = useMemo<Space[]>(() => {
    const out: Space[] = [{ key: "ws", agentId: null, label: "Whole workspace", kind: "workspace" }];
    for (const a of agents) {
      const isSlack = a.provider === "slack";
      const name = (a.display_name ?? "").trim() || a.external_agent_id || a.id;
      out.push({
        key: a.id,
        agentId: a.id,
        label: isSlack ? `#${name}` : name,
        kind: isSlack ? "channel" : "agent",
      });
    }
    return out;
  }, [agents]);

  const latestFor = useCallback(
    (agentId: string | null): IndexRow | null => {
      const matches = indexes.filter((i) => (i.agent_id ?? null) === agentId);
      if (matches.length === 0) return null;
      return matches.reduce((a, b) =>
        (a.created_at ?? "") >= (b.created_at ?? "") ? a : b,
      );
    },
    [indexes],
  );

  const build = useCallback(
    async (space: Space) => {
      setBusyKey(space.key);
      try {
        const res = await fetch(`${base}/graphrag/index`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agent_id: space.agentId, max_docs: maxDocs }),
        });
        const body = await res.json().catch(() => ({}));
        if (res.status !== 202) {
          toast({
            variant: "error",
            message: body?.detail ?? body?.error?.message ?? `Build failed (${res.status})`,
          });
          return;
        }
        toast({ variant: "success", message: `GraphRAG index started for ${space.label}` });
        await loadIndexes();
      } finally {
        setBusyKey(null);
      }
    },
    [base, maxDocs, toast, loadIndexes],
  );

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-h3 text-foreground">GraphRAG indexes</h1>
          <p className="max-w-2xl text-p text-muted-foreground">
            Build a Microsoft GraphRAG index for a memory space (all-Cohere). Once ready, chat with
            the <span className="font-medium text-foreground">MS GraphRAG</span> retrieval mode
            scoped to that space for global-search answers over community reports.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-caption text-muted-foreground">
            Max docs
            <Input
              type="number"
              min={4}
              max={5000}
              value={maxDocs}
              onChange={(e) => setMaxDocs(Number(e.target.value) || 200)}
              className="h-8 w-24"
            />
          </label>
          <Button variant="outline" size="sm" onClick={() => void loadAll()} disabled={loading}>
            Refresh
          </Button>
        </div>
      </header>

      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <table className="w-full text-p">
          <thead className="bg-secondary/40 text-caption text-muted-foreground">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Memory space</th>
              <th className="px-4 py-2 text-left font-medium">Status</th>
              <th className="px-4 py-2 text-left font-medium">Stats</th>
              <th className="px-4 py-2 text-right font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {spaces.map((s) => {
              const idx = latestFor(s.agentId);
              const status = idx?.status ?? "none";
              const stats = (idx?.stats ?? {}) as Record<string, number>;
              const active = status === "pending" || status === "running";
              return (
                <tr key={s.key} className="border-t border-border">
                  <td className="px-4 py-2">
                    <span className="text-foreground">{s.label}</span>
                    {s.kind !== "workspace" && (
                      <Badge variant="outline" className="ml-2">
                        {s.kind}
                      </Badge>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    {status === "none" ? (
                      <span className="text-muted-foreground">not built</span>
                    ) : (
                      <Badge variant={statusVariant(status)}>{status}</Badge>
                    )}
                    {status === "failed" && idx?.failure_reason ? (
                      <span className="ml-2 text-caption text-destructive">
                        {idx.failure_reason.slice(0, 80)}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-2 text-caption text-muted-foreground">
                    {status === "ready"
                      ? `${stats.entities ?? 0} entities · ${stats.relationships ?? 0} rels · ${stats.community_reports ?? 0} reports`
                      : "—"}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Button
                      size="sm"
                      variant={status === "ready" ? "outline" : "default"}
                      disabled={active || busyKey === s.key}
                      onClick={() => void build(s)}
                    >
                      {active
                        ? "Building…"
                        : busyKey === s.key
                          ? "Starting…"
                          : status === "ready" || status === "failed"
                            ? "Rebuild"
                            : "Build index"}
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {loading && <p className="text-caption text-muted-foreground">Loading…</p>}
    </div>
  );
}
