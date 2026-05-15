"use client";

import { Bot, CloudDownload, Sparkles } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { cn } from "@/lib/utils";

type NorthAgent = {
  id: string;
  display_name: string;
  external_agent_id: string;
  provider: string;
};

export function AgentsPanel({ workspaceId }: { workspaceId: string }) {
  const [agents, setAgents] = useState<NorthAgent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const res = await fetch(`/api/v1/workspaces/${workspaceId}/north/agents`, { cache: "no-store" });
    const body = (await res.json().catch(() => ({}))) as { items?: NorthAgent[]; error?: { message?: string } };
    if (!res.ok) {
      setError(body.error?.message ?? `HTTP ${res.status}`);
      return;
    }
    setAgents(body.items ?? []);
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const syncFromNorth = async () => {
    setBusy("sync");
    setError(null);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/north/agents/sync`, {
        method: "POST",
        cache: "no-store",
      });
      const body = (await res.json().catch(() => ({}))) as { error?: { message?: string } };
      if (!res.ok) {
        setError(body.error?.message ?? `HTTP ${res.status}`);
        return;
      }
      await load();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-title-2 text-primary">Agents</h1>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1 rounded-md border border-border-subtle px-3 py-1.5 text-body text-secondary",
            "hover:bg-surface-raised hover:text-primary disabled:opacity-50",
          )}
          onClick={() => void syncFromNorth()}
          disabled={busy === "sync"}
        >
          <CloudDownload className="h-4 w-4" strokeWidth={1.5} aria-hidden />
          Sync from North
        </button>
      </div>
      <p className="max-w-prose text-body text-muted">
        Register North agents from your configured instance, import conversations into the standard ingestion pipeline, and
        run offline dreaming scoped to each agent.
      </p>
      {error ? (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-body text-destructive">
          {error}
        </p>
      ) : null}
      {agents.length === 0 && !error ? (
        <p className="text-caption text-muted">No agents yet — sync from North or add pipeline_settings credentials.</p>
      ) : null}
      <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle bg-surface">
        {agents.map((a) => (
          <li key={a.id} className="flex items-center justify-between gap-3 px-3 py-3">
            <div className="flex min-w-0 items-center gap-2">
              <Bot className="h-5 w-5 shrink-0 text-muted" strokeWidth={1.5} aria-hidden />
              <div className="min-w-0">
                <p className="truncate text-body text-primary">{a.display_name || a.external_agent_id}</p>
                <p className="truncate text-caption text-muted">
                  {a.provider} · {a.external_agent_id}
                </p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Link
                href={`/agents/${a.id}`}
                className="rounded-md border border-border-subtle px-2 py-1 text-caption text-secondary hover:bg-surface-raised hover:text-primary"
              >
                Open
              </Link>
              <button
                type="button"
                className="inline-flex items-center gap-1 rounded-md border border-border-subtle px-2 py-1 text-caption text-secondary hover:bg-surface-raised hover:text-primary"
                onClick={async () => {
                  setBusy(`dream:${a.id}`);
                  setError(null);
                  try {
                    const res = await fetch(`/api/v1/workspaces/${workspaceId}/north/agents/${a.id}/dream`, {
                      method: "POST",
                    });
                    const body = (await res.json().catch(() => ({}))) as { error?: { message?: string } };
                    if (!res.ok) {
                      setError(body.error?.message ?? `Dream HTTP ${res.status}`);
                    }
                  } finally {
                    setBusy(null);
                  }
                }}
                disabled={busy?.startsWith("dream")}
              >
                <Sparkles className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden />
                Dream
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
