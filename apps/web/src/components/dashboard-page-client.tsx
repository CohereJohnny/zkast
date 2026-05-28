"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { LayoutDashboard } from "lucide-react";

import { AgentPicker } from "@/components/filters/agent-picker";
import { readApiErrorMessage } from "@/lib/api-error-message";
import { cn } from "@/lib/utils";

type Counts = Record<string, number>;

type DashboardPayload = {
  workspace_id: string;
  busy: boolean;
  busy_reasons: string[];
  counts: Counts;
  postgres?: {
    documents_by_source?: Record<string, number>;
    documents_by_status?: Record<string, number>;
    ingestion_runs_by_status?: Record<string, number>;
    entities_by_agent?: { agent_id: string | null; count: number }[];
    embeddings_by_agent?: {
      agent_id: string | null;
      index_kind: string;
      count: number;
    }[];
    wiki?: { spaces: number; pages: number };
    chat?: { sessions: number; messages: number };
    global_graph?: { entities: number; relationships: number; graphiti_entity_maps: number };
    ingestion_logs?: number;
  };
  storage?: {
    embeddings_by_kind?: Record<string, number>;
    raw_chunk_index?: {
      episodes_total: number;
      embeddings_total: number;
      missing: number;
    };
    falkor_graphs?: {
      graph_name: string;
      node_count: number | null;
      scope: string;
    }[];
  };
  usage?: {
    workspace_total?: { tokens_in: number; tokens_out: number; event_count: number };
    by_source?: Record<string, { tokens_in: number; tokens_out: number; event_count: number }>;
  };
  agents?: AgentSummary[];
  filters?: { agent_id?: string | null; conversation_id?: string | null };
  selection?: {
    agent?: AgentSummary | null;
    conversation?: ConversationRow | null;
  };
  drift_warnings?: string[];
};

type ConversationRow = {
  north_conversation_id: string;
  document_id?: string;
  document_status?: string;
  notes: number;
  amem_embeddings: number;
  ingest_digest?: string | null;
};

type AgentSummary = {
  agent_id: string;
  display_name: string;
  external_agent_id?: string;
  stats?: {
    imported_documents: number;
    derived_notes: number;
    cached_conversations: number;
    note_amem_embeddings: number;
  };
  graph?: { entities: number; relationships: number; graphiti_entity_maps: number };
  notes?: number;
  wiki_spaces?: number;
  embeddings_by_kind?: Record<string, number>;
  usage_by_source?: Record<string, { tokens_in: number; tokens_out: number }>;
  memory_space_graph?: string;
  conversations?: ConversationRow[];
};

function KpiTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-border bg-secondary px-4 py-3">
      <p className="text-caption text-muted-foreground">{label}</p>
      <p className="mt-1 text-h4 font-semibold tabular-nums text-foreground">{value}</p>
      {hint ? <p className="mt-0.5 text-caption text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function RecordList({ title, rows }: { title: string; rows: [string, number][] }) {
  if (!rows.length) return null;
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="text-h5 font-semibold text-foreground">{title}</h2>
      <dl className="mt-3 grid gap-2 text-p">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 border-b border-border/60 py-1 last:border-0">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="font-mono text-foreground tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function DashboardPageClient({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const agentFilter = searchParams.get("agent_id") || "";
  const conversationFilter = searchParams.get("conversation_id") || "";

  const [data, setData] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const qs = new URLSearchParams();
      if (agentFilter) qs.set("agent_id", agentFilter);
      if (conversationFilter) qs.set("conversation_id", conversationFilter);
      const suffix = qs.toString() ? `?${qs.toString()}` : "";
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/dashboard${suffix}`,
        { cache: "no-store" },
      );
      const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        setError(readApiErrorMessage(body, `HTTP ${res.status}`));
        return;
      }
      setData(body as DashboardPayload);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dashboard");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, agentFilter, conversationFilter]);

  useEffect(() => {
    setLoading(true);
    void load();
    const t = window.setInterval(() => void load(), 8000);
    return () => window.clearInterval(t);
  }, [load]);

  const counts = data?.counts ?? {};
  const usage = data?.usage?.workspace_total;
  const tokensTotal = (usage?.tokens_in ?? 0) + (usage?.tokens_out ?? 0);

  const selectedAgent = useMemo(() => {
    if (!data?.agents?.length) return null;
    if (agentFilter) {
      return data.agents.find((a) => a.agent_id === agentFilter) ?? data.selection?.agent ?? null;
    }
    return null;
  }, [data, agentFilter]);

  const setAgentFilter = (id: string | null) => {
    const qs = new URLSearchParams(searchParams.toString());
    if (id) qs.set("agent_id", id);
    else qs.delete("agent_id");
    qs.delete("conversation_id");
    router.replace(`/dashboard?${qs.toString()}`);
  };

  const setConversationFilter = (cid: string | null) => {
    const qs = new URLSearchParams(searchParams.toString());
    if (!agentFilter) return;
    if (cid) qs.set("conversation_id", cid);
    else qs.delete("conversation_id");
    router.replace(`/dashboard?${qs.toString()}`);
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-auto p-2">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-h4 text-foreground">
            <LayoutDashboard className="h-6 w-6 shrink-0" strokeWidth={1.5} aria-hidden />
            Dashboard
          </h1>
          <p className="mt-1 max-w-2xl text-p text-muted-foreground">
            Workspace memory inventory: sources, indices, graph stores, jobs, and token usage.
            Drill down by agent and conversation.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <AgentPicker
            workspaceId={workspaceId}
            value={agentFilter}
            onChange={(id) => setAgentFilter(id || null)}
            allowClear
            label="Filter by agent"
            placeholder="All agents (workspace)"
          />
          <Link
            href="/jobs"
            className="rounded-md border border-border px-3 py-2 text-p text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            Jobs
          </Link>
          <Link
            href="/settings/diagnostics"
            className="rounded-md border border-border px-3 py-2 text-p text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            Diagnostics
          </Link>
        </div>
      </div>

      {error ? (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-p text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      {loading && !data ? (
        <p className="text-p text-muted-foreground" role="status">
          Loading dashboard…
        </p>
      ) : null}

      {data?.busy ? (
        <p className="rounded-md border border-caution/40 bg-caution/10 px-3 py-2 text-caption text-foreground">
          Active jobs: {data.busy_reasons.join("; ")}
        </p>
      ) : null}

      {data?.drift_warnings?.length ? (
        <div className="rounded-lg border border-caution/40 bg-caution/10 p-4">
          <h2 className="text-h5 font-semibold text-foreground">Health warnings</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-caption text-muted-foreground">
            {data.drift_warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {data ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <KpiTile label="Documents" value={counts.documents ?? 0} hint="All sources" />
            <KpiTile label="Notes" value={counts.atomic_notes ?? 0} />
            <KpiTile
              label="Embeddings"
              value={counts.retrieval_embeddings ?? 0}
              hint="pgvector rows"
            />
            <KpiTile
              label="Tokens (tracked)"
              value={tokensTotal.toLocaleString()}
              hint={`${usage?.tokens_in ?? 0} in / ${usage?.tokens_out ?? 0} out`}
            />
            <KpiTile label="Entities (PG)" value={counts.entities ?? 0} />
            <KpiTile label="Relationships (PG)" value={counts.relationships ?? 0} />
            <KpiTile label="Agents" value={counts.north_agents ?? 0} />
            <KpiTile label="Eval runs" value={counts.chat_eval_runs ?? 0} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <RecordList
              title="Documents by source"
              rows={Object.entries(data.postgres?.documents_by_source ?? {})}
            />
            <RecordList
              title="Embeddings by kind"
              rows={Object.entries(data.storage?.embeddings_by_kind ?? {})}
            />
            <RecordList
              title="Usage by source"
              rows={Object.entries(data.usage?.by_source ?? {}).map(([k, v]) => [
                k,
                (v.tokens_in ?? 0) + (v.tokens_out ?? 0),
              ])}
            />
            <div className="rounded-lg border border-border bg-card p-4">
              <h2 className="text-h5 font-semibold text-foreground">Storage split</h2>
              <dl className="mt-3 space-y-2 text-p">
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Postgres content rows (est.)</dt>
                  <dd className="font-mono tabular-nums">
                    {Object.values(counts).reduce((a, b) => a + b, 0).toLocaleString()}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Raw chunk coverage</dt>
                  <dd className="font-mono tabular-nums">
                    {data.storage?.raw_chunk_index?.embeddings_total ?? 0} /{" "}
                    {data.storage?.raw_chunk_index?.episodes_total ?? 0}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Wiki pages</dt>
                  <dd className="font-mono tabular-nums">{data.postgres?.wiki?.pages ?? 0}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Chat messages</dt>
                  <dd className="font-mono tabular-nums">{data.postgres?.chat?.messages ?? 0}</dd>
                </div>
              </dl>
              <h3 className="mt-4 text-caption font-semibold uppercase tracking-wider text-muted-foreground">
                FalkorDB graphs
              </h3>
              <ul className="mt-2 space-y-1 text-caption">
                {(data.storage?.falkor_graphs ?? []).map((g) => (
                  <li key={g.graph_name} className="flex justify-between gap-2">
                    <span className="truncate font-mono text-muted-foreground" title={g.graph_name}>
                      {g.scope}: {g.graph_name.slice(0, 24)}…
                    </span>
                    <span className="tabular-nums text-foreground">
                      {g.node_count != null ? g.node_count : "—"}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="rounded-lg border border-border bg-card p-4">
            <h2 className="text-h5 font-semibold text-foreground">Agents (isolated memory spaces)</h2>
            <p className="mt-1 text-caption text-muted-foreground">
              Each agent has its own Falkor graph, scoped entities, and filtered embeddings.
            </p>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-caption">
                <thead>
                  <tr className="border-b border-border text-muted-foreground">
                    <th className="py-2 pr-4">Agent</th>
                    <th className="py-2 pr-4">Docs</th>
                    <th className="py-2 pr-4">Notes</th>
                    <th className="py-2 pr-4">A-MEM</th>
                    <th className="py-2 pr-4">Graph (PG)</th>
                    <th className="py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.agents ?? []).map((a) => (
                    <tr
                      key={a.agent_id}
                      className={cn(
                        "border-b border-border/60",
                        agentFilter === a.agent_id && "bg-secondary/80",
                      )}
                    >
                      <td className="py-2 pr-4 font-medium text-foreground">{a.display_name}</td>
                      <td className="py-2 pr-4 tabular-nums">{a.stats?.imported_documents ?? 0}</td>
                      <td className="py-2 pr-4 tabular-nums">{a.notes ?? a.stats?.derived_notes ?? 0}</td>
                      <td className="py-2 pr-4 tabular-nums">
                        {a.stats?.note_amem_embeddings ?? 0}
                      </td>
                      <td className="py-2 pr-4 tabular-nums">{a.graph?.entities ?? 0}</td>
                      <td className="py-2">
                        <button
                          type="button"
                          className="text-link hover:underline"
                          onClick={() => setAgentFilter(a.agent_id)}
                        >
                          Drill down
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {selectedAgent ? (
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-h5 font-semibold text-foreground">
                  {selectedAgent.display_name}
                </h2>
                <div className="flex flex-wrap gap-2 text-caption">
                  <Link href={`/agents/${selectedAgent.agent_id}`} className="text-link hover:underline">
                    Agent detail
                  </Link>
                  <Link
                    href={`/notes?agentId=${selectedAgent.agent_id}`}
                    className="text-link hover:underline"
                  >
                    Notes
                  </Link>
                  <Link
                    href={`/graph?agent_id=${selectedAgent.agent_id}`}
                    className="text-link hover:underline"
                  >
                    Graph
                  </Link>
                  <Link
                    href={`/chat?agent_id=${selectedAgent.agent_id}`}
                    className="text-link hover:underline"
                  >
                    Chat
                  </Link>
                </div>
              </div>
              <p className="mt-1 font-mono text-caption text-muted-foreground">
                Memory graph: {selectedAgent.memory_space_graph}
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <KpiTile label="Conversations" value={selectedAgent.stats?.cached_conversations ?? 0} />
                <KpiTile label="Wiki spaces" value={selectedAgent.wiki_spaces ?? 0} />
                <KpiTile
                  label="Agent tokens"
                  value={Object.values(selectedAgent.usage_by_source ?? {}).reduce(
                    (sum, u) => sum + (u.tokens_in ?? 0) + (u.tokens_out ?? 0),
                    0,
                  )}
                />
              </div>
              <h3 className="mt-4 text-caption font-semibold uppercase tracking-wider text-muted-foreground">
                Conversations
              </h3>
              <ul className="mt-2 divide-y divide-border rounded-md border border-border">
                {(selectedAgent.conversations ?? []).map((c) => (
                  <li key={c.north_conversation_id}>
                    <button
                      type="button"
                      className={cn(
                        "flex w-full flex-col gap-1 px-3 py-2 text-left text-p hover:bg-secondary",
                        conversationFilter === c.north_conversation_id && "bg-secondary",
                      )}
                      onClick={() => setConversationFilter(c.north_conversation_id)}
                    >
                      <span className="font-mono text-caption text-foreground">
                        {c.north_conversation_id}
                      </span>
                      <span className="text-caption text-muted-foreground">
                        {c.notes} notes · {c.amem_embeddings} A-MEM · status {c.document_status}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              {conversationFilter && data.selection?.conversation ? (
                <div className="mt-4 rounded-md border border-input bg-secondary/50 p-3 text-caption">
                  <p className="font-medium text-foreground">Selected conversation</p>
                  <p className="mt-1 font-mono text-muted-foreground">{conversationFilter}</p>
                  <p className="mt-2 text-muted-foreground">
                    Document {data.selection.conversation.document_id} ·{" "}
                    {data.selection.conversation.notes} notes ·{" "}
                    {data.selection.conversation.amem_embeddings} embeddings
                  </p>
                  <Link
                    href={`/documents?highlight=${data.selection.conversation.document_id}`}
                    className="mt-2 inline-block text-link hover:underline"
                  >
                    Open document
                  </Link>
                </div>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
