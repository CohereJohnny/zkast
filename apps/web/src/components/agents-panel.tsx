"use client";

import { Bot, CloudDownload, Search, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DreamJobStatus } from "@/components/dream-job-status";
import { useToast } from "@/components/feedback-provider";
import { readApiErrorMessage } from "@/lib/api-error-message";
import { useJobEvents } from "@/lib/job-events";
import { cn } from "@/lib/utils";

type NorthAgent = {
  id: string;
  display_name: string;
  external_agent_id: string;
  provider: string;
};

export function AgentsPanel({ workspaceId }: { workspaceId: string }) {
  const toast = useToast();
  const { registerActiveJob } = useJobEvents();
  const [agents, setAgents] = useState<NorthAgent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [pipelineCount, setPipelineCount] = useState<number | null>(null);
  const [pipelineWorkspaceEcho, setPipelineWorkspaceEcho] = useState<string | null>(null);
  const [activeDreamJob, setActiveDreamJob] = useState<{ agentId: string; jobId: string } | null>(
    null,
  );
  const [filter, setFilter] = useState("");

  const filteredAgents = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return agents;
    return agents.filter((a) => {
      const display = (a.display_name || "").toLowerCase();
      const external = (a.external_agent_id || "").toLowerCase();
      const id = a.id.toLowerCase();
      return display.includes(q) || external.includes(q) || id.includes(q);
    });
  }, [agents, filter]);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/north/agents`, { cache: "no-store" });
      let body: unknown = {};
      try {
        body = await res.json();
      } catch {
        body = null;
      }
      if (
        !res.ok ||
        body === null ||
        typeof body !== "object" ||
        Array.isArray(body)
      ) {
        setNotice(null);
        setPipelineCount(null);
        setPipelineWorkspaceEcho(null);
        setError(
          !res.ok
            ? readApiErrorMessage(
                (typeof body === "object" && body !== null ? body : {}) as Record<string, unknown>,
                `HTTP ${res.status}`,
              )
            : "Agents list response was not valid JSON.",
        );
        return;
      }
      const typed = body as {
        items?: NorthAgent[];
        count?: number;
        workspace_id?: string;
      };
      const items = Array.isArray(typed.items) ? typed.items : [];
      setAgents(items);
      const rowTotal = typeof typed.count === "number" ? typed.count : items.length;
      setPipelineCount(Number.isFinite(rowTotal) ? rowTotal : items.length);
      const rawEcho = typed.workspace_id;
      const echo =
        typeof rawEcho === "string" && rawEcho.trim().length > 0 ? rawEcho.trim() : workspaceId;
      setPipelineWorkspaceEcho(echo);
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const syncFromNorth = async () => {
    setBusy("sync");
    setError(null);
    setNotice(null);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/north/agents/sync`, {
        method: "POST",
        cache: "no-store",
      });
      const ct = res.headers.get("content-type") ?? "";
      if (res.ok && !ct.includes("application/json")) {
        setError(
          `Sync returned a non-JSON response (${ct.slice(0, 96) || "no content-type"}). Check PIPELINE_INTERNAL_URL and that the pipeline service is running.`,
        );
        return;
      }
      const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        setError(readApiErrorMessage(body, `HTTP ${res.status}`));
        return;
      }
      const agentsOut = Array.isArray(body.agents) ? (body.agents as unknown[]) : null;
      const hasNewMeta = typeof body.remote_count === "number" && typeof body.registered_count === "number";
      if (res.ok && !hasNewMeta && agentsOut && agentsOut.length === 0) {
        setError(
          "Sync returned 0 agents and no remote/registered counts — the pipeline is almost certainly an old image. Rebuild it: `docker compose build pipeline && docker compose up -d pipeline` (and rebuild `web` if you run it in Docker).",
        );
        await load();
        return;
      }
      const remoteCount = typeof body.remote_count === "number" ? body.remote_count : null;
      const registeredCount = typeof body.registered_count === "number" ? body.registered_count : null;
      const sampleKeys = Array.isArray(body.sample_top_level_keys)
        ? (body.sample_top_level_keys as unknown[]).filter((k): k is string => typeof k === "string")
        : [];
      const sampleTypes = body.sample_field_types;
      const typesHint =
        sampleTypes && typeof sampleTypes === "object" && !Array.isArray(sampleTypes)
          ? ` Field types (first row): ${JSON.stringify(sampleTypes)}.`
          : "";
      if (remoteCount !== null && registeredCount !== null && remoteCount > 0 && registeredCount === 0) {
        const keyHint =
          sampleKeys.length > 0 ? ` First agent object has keys: ${sampleKeys.slice(0, 40).join(", ")}.` : "";
        setError(
          `North listed ${remoteCount} agent row(s) but zkast could not read an external id from them.${keyHint}${typesHint} Rebuild the pipeline from the latest code and try again, or share this message with the maintainers.`,
        );
        await load();
        return;
      }
      if (registeredCount !== null && registeredCount > 0) {
        setNotice(
          remoteCount !== null && remoteCount !== registeredCount
            ? `Registered ${registeredCount} agent(s) (${remoteCount} row(s) from North).`
            : `Registered ${registeredCount} agent(s) from North.`,
        );
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
        Register North agents from your configured instance and import conversations into the same document and
        ingestion pipeline as PDFs. Each import is scoped to the selected agent.
      </p>
      {agents.length > 0 ? (
        <div className="relative max-w-md">
          <label htmlFor="agents-filter" className="sr-only">
            Filter agents
          </label>
          <Search
            className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
            strokeWidth={1.5}
            aria-hidden
          />
          <input
            id="agents-filter"
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter agents by name or id…"
            autoComplete="off"
            spellCheck={false}
            className="w-full rounded-md border border-border-strong bg-surface py-1.5 pl-8 pr-8 text-body text-secondary placeholder:text-muted/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
          />
          {filter ? (
            <button
              type="button"
              onClick={() => setFilter("")}
              aria-label="Clear filter"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted hover:bg-surface-raised hover:text-primary"
            >
              <X className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden />
            </button>
          ) : null}
        </div>
      ) : null}
      {error ? (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-body text-destructive">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-body text-secondary">
          {notice}
        </p>
      ) : null}
      {loading ? (
        <p className="text-caption text-muted" role="status">
          Loading agents…
        </p>
      ) : null}
      {agents.length === 0 && !error && !loading ? (
        <div className="max-w-prose space-y-2 text-caption text-muted">
          <p>
            No agents are registered for this workspace in the <strong>pipeline database</strong> yet. The list
            above is loaded from Postgres via the pipeline (not from North directly). Use{" "}
            <strong>Sync from North</strong> after North is configured in Settings.
          </p>
          <p>
            The pipeline reports <strong>{pipelineCount === null ? "—" : pipelineCount}</strong> stored North agent
            row(s) in Postgres for this workspace. <strong>0</strong> means nothing has been written yet — click{" "}
            <strong>Sync from North</strong> (Test North only checks the North API; it does not register agents here).
          </p>
          {pipelineWorkspaceEcho &&
          pipelineWorkspaceEcho.trim() !== "" &&
          pipelineWorkspaceEcho.trim() !== workspaceId.trim() ? (
            <p>
              Workspace mismatch: page is <code className="text-secondary">{workspaceId}</code> but the pipeline
              echoed <code className="text-secondary">{pipelineWorkspaceEcho}</code>. Align{" "}
              <code className="text-secondary">DATABASE_URL</code> / default workspace between web and pipeline.
            </p>
          ) : null}
          <p>
            If <strong>Test North</strong> lists many agents but this count stays <strong>0</strong> after sync,
            rebuild the <strong>pipeline</strong> image from the current repo (North JSON shape / sync metadata).
          </p>
        </div>
      ) : null}
      {agents.length > 0 && filteredAgents.length === 0 ? (
        <p className="text-caption text-muted" role="status">
          No agents match &ldquo;{filter}&rdquo;. Clear the filter to see all{" "}
          {agents.length} agent(s).
        </p>
      ) : null}
      <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle bg-surface">
        {filteredAgents.map((a) => (
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
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <Link
                href={`/agents/${a.id}`}
                className="rounded-md border border-border-subtle px-2 py-1 text-caption text-secondary hover:bg-surface-raised hover:text-primary"
              >
                Open
              </Link>
              <Link
                href={`/notes?agentId=${encodeURIComponent(a.id)}`}
                className="rounded-md border border-border-subtle px-2 py-1 text-caption text-secondary hover:bg-surface-raised hover:text-primary"
              >
                Notes
              </Link>
              <Link
                href={`/graph?agent_id=${encodeURIComponent(a.id)}`}
                className="rounded-md border border-border-subtle px-2 py-1 text-caption text-secondary hover:bg-surface-raised hover:text-primary"
              >
                Graph
              </Link>
              <Link
                href={`/chat?agent_id=${encodeURIComponent(a.id)}`}
                className="rounded-md border border-border-subtle px-2 py-1 text-caption text-secondary hover:bg-surface-raised hover:text-primary"
              >
                Chat
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
                    const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
                    if (!res.ok) {
                      setError(readApiErrorMessage(body, `Dream HTTP ${res.status}`));
                      toast({
                        variant: "error",
                        message: "Dream failed to queue",
                        description: readApiErrorMessage(body, `HTTP ${res.status}`),
                      });
                    } else {
                      const jobId = typeof body.job_id === "string" ? body.job_id : null;
                      if (jobId) {
                        registerActiveJob(jobId, workspaceId, null, "dreaming");
                        setActiveDreamJob({ agentId: a.id, jobId });
                        const label = a.display_name || a.external_agent_id;
                        toast({
                          variant: "success",
                          message: "Dream job queued",
                          description: `${label} — watch progress on Jobs or the build log below`,
                        });
                      }
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
      {activeDreamJob ? (
        <DreamJobStatus
          workspaceId={workspaceId}
          agentId={activeDreamJob.agentId}
          jobId={activeDreamJob.jobId}
          onDone={(status) => {
            if (status === "succeeded") {
              toast({
                variant: "success",
                message: "Dream job completed",
                description: "Memory links and embeddings were updated for this agent.",
              });
            } else if (status === "failed") {
              toast({
                variant: "error",
                message: "Dream job failed",
                description: "See Jobs or the build log for details.",
              });
            }
          }}
        />
      ) : null}
    </div>
  );
}
