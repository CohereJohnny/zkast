"use client";

import { ArrowLeft, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { cn } from "@/lib/utils";

type CacheRow = {
  north_conversation_id: string;
  fetched_at: string | null;
};

export function AgentDetailPanel({ workspaceId, agentId }: { workspaceId: string; agentId: string }) {
  const [rows, setRows] = useState<CacheRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(
    async (refresh: boolean) => {
      setError(null);
      const q = refresh ? "?refresh=true" : "";
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/north/agents/${agentId}/conversations${q}`,
        { cache: "no-store" },
      );
      const body = (await res.json().catch(() => ({}))) as {
        items?: CacheRow[] | unknown[];
        error?: { message?: string };
        source?: string;
      };
      if (!res.ok) {
        setError(body.error?.message ?? `HTTP ${res.status}`);
        return;
      }
      const items = body.items ?? [];
      const normalized: CacheRow[] = items.map((it) => {
        if (it && typeof it === "object" && "north_conversation_id" in it) {
          return it as CacheRow;
        }
        const o = it as Record<string, unknown>;
        const id = String(o.id ?? o.conversation_id ?? "");
        return { north_conversation_id: id, fetched_at: null };
      });
      setRows(normalized.filter((r) => r.north_conversation_id));
    },
    [workspaceId, agentId],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  const importConv = async (cid: string) => {
    setBusy(cid);
    setError(null);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/north/agents/${agentId}/conversations/${encodeURIComponent(cid)}/import`,
        { method: "POST" },
      );
      const body = (await res.json().catch(() => ({}))) as { error?: { message?: string }; job_id?: string | null };
      if (!res.ok) {
        setError(body.error?.message ?? `Import HTTP ${res.status}`);
        return;
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <Link href="/agents" className="inline-flex items-center gap-1 text-caption text-muted hover:text-primary">
        <ArrowLeft className="h-4 w-4" strokeWidth={1.5} aria-hidden />
        All agents
      </Link>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-title-2 text-primary">Agent conversations</h1>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1 rounded-md border border-border-subtle px-3 py-1.5 text-body text-secondary",
            "hover:bg-surface-raised hover:text-primary disabled:opacity-50",
          )}
          onClick={() => void load(true)}
          disabled={busy === "refresh"}
        >
          <RefreshCw className="h-4 w-4" strokeWidth={1.5} aria-hidden />
          Refresh from North
        </button>
      </div>
      {error ? (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-body text-destructive">
          {error}
        </p>
      ) : null}
      <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle bg-surface">
        {rows.map((r) => (
          <li key={r.north_conversation_id} className="flex items-center justify-between gap-3 px-3 py-2">
            <span className="truncate font-mono text-caption text-secondary">{r.north_conversation_id}</span>
            <button
              type="button"
              className="shrink-0 rounded-md border border-border-subtle px-2 py-1 text-caption text-secondary hover:bg-surface-raised hover:text-primary disabled:opacity-50"
              disabled={busy === r.north_conversation_id}
              onClick={() => void importConv(r.north_conversation_id)}
            >
              Import
            </button>
          </li>
        ))}
      </ul>
      {rows.length === 0 && !error ? (
        <p className="text-caption text-muted">No cached conversations — click refresh to pull from North.</p>
      ) : null}
    </div>
  );
}
