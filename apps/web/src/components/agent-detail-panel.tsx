"use client";

import { ArrowLeft, ChevronDown, ChevronRight, RefreshCw, Sparkles } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ConversationMemoryTelemetry,
  type ConversationMemoryStats,
} from "@/components/conversation-memory-telemetry";
import { DreamJobStatus } from "@/components/dream-job-status";
import { readApiErrorMessage } from "@/lib/api-error-message";
import { useJobEvents } from "@/lib/job-events";
import { cn } from "@/lib/utils";

type SyncStatus = "not_synced" | "synced" | "syncing" | "outdated";

type CacheRow = {
  north_conversation_id: string;
  fetched_at: string | null;
  title?: string | null;
  sync_status?: SyncStatus;
  document_id?: string | null;
  memory?: ConversationMemoryStats | null;
};

type PreviewReady = {
  status: "ready";
  title: string;
  message_count: number;
  preview_truncated: boolean;
  messages: { role: string; excerpt: string }[];
};

type PreviewEntry = PreviewReady | { status: "loading" } | { status: "error"; message: string };

function normalizeConversationRow(it: unknown): CacheRow | null {
  if (!it || typeof it !== "object") return null;
  const o = it as Record<string, unknown>;
  if ("north_conversation_id" in o && o.north_conversation_id) {
    const id = String(o.north_conversation_id);
    const fetched = o.fetched_at != null ? String(o.fetched_at) : null;
    let title: string | null = null;
    const pl = o.payload;
    if (pl && typeof pl === "object") {
      const p = pl as Record<string, unknown>;
      const t = String(p.title ?? p.name ?? p.displayTitle ?? "").trim();
      title = t || null;
    }
    return {
      north_conversation_id: id,
      fetched_at: fetched,
      title,
      ...importFieldsFromApi(o),
    };
  }
  const id = String(
    o.id ?? o.conversation_id ?? o.conversationId ?? o.thread_id ?? o.threadId ?? "",
  );
  if (!id) return null;
  const t = String(o.title ?? o.name ?? o.displayTitle ?? "").trim();
  const base = { north_conversation_id: id, fetched_at: null, title: t || null };
  return { ...base, ...importFieldsFromApi(o) };
}

function importFieldsFromApi(o: Record<string, unknown>): Partial<CacheRow> {
  const sync = o.sync_status;
  const mem = o.memory;
  return {
    sync_status: typeof sync === "string" ? (sync as SyncStatus) : undefined,
    document_id: o.document_id != null ? String(o.document_id) : null,
    memory:
      mem && typeof mem === "object"
        ? {
            notes: typeof (mem as Record<string, unknown>).notes === "number" ? Number((mem as Record<string, unknown>).notes) : undefined,
            amem_embeddings:
              typeof (mem as Record<string, unknown>).amem_embeddings === "number"
                ? Number((mem as Record<string, unknown>).amem_embeddings)
                : undefined,
            document_status:
              typeof (mem as Record<string, unknown>).document_status === "string"
                ? String((mem as Record<string, unknown>).document_status)
                : undefined,
            ingest_digest:
              typeof (mem as Record<string, unknown>).ingest_digest === "string"
                ? String((mem as Record<string, unknown>).ingest_digest)
                : null,
            cached: (mem as Record<string, unknown>).cached === true,
          }
        : null,
  };
}

function ConversationAction({
  row,
  agentId,
  busy,
  onImport,
}: {
  row: CacheRow;
  agentId: string;
  busy: boolean;
  onImport: () => void;
}) {
  const status = row.sync_status ?? "not_synced";
  if (status === "synced") {
    return (
      <Link
        href={`/notes?agentId=${encodeURIComponent(agentId)}`}
        className="shrink-0 text-caption text-muted-foreground hover:text-foreground"
      >
        Notes
      </Link>
    );
  }
  if (status === "syncing") {
    return <span className="shrink-0 text-caption text-muted-foreground">Importing…</span>;
  }
  const label = status === "outdated" ? "Re-import" : "Import";
  return (
    <button
      type="button"
      className="shrink-0 rounded-md border border-border px-2 py-1 text-caption text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-50"
      disabled={busy}
      onClick={onImport}
    >
      {busy ? "…" : label}
    </button>
  );
}

export function AgentDetailPanel({ workspaceId, agentId }: { workspaceId: string; agentId: string }) {
  const { registerActiveJob, requestOpenLogConsole } = useJobEvents();
  const runRef = useRef(0);
  const [rows, setRows] = useState<CacheRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [importNotice, setImportNotice] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [previewById, setPreviewById] = useState<Record<string, PreviewEntry>>({});
  const [stats, setStats] = useState<{
    imported_documents: number;
    derived_notes: number;
    cached_conversations: number;
    note_amem_embeddings: number;
    import_digest?: string | null;
  } | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [dreamJobId, setDreamJobId] = useState<string | null>(null);
  const [dreamBusy, setDreamBusy] = useState(false);

  const loadPreview = useCallback(
    async (cid: string) => {
      setPreviewById((p) => ({ ...p, [cid]: { status: "loading" } }));
      try {
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/north/agents/${agentId}/conversations/${encodeURIComponent(cid)}/preview`,
          { cache: "no-store" },
        );
        const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
        if (!res.ok) {
          setPreviewById((p) => ({
            ...p,
            [cid]: { status: "error", message: readApiErrorMessage(body, `HTTP ${res.status}`) },
          }));
          return;
        }
        const title = String(body.title ?? "");
        const message_count = typeof body.message_count === "number" ? body.message_count : 0;
        const preview_truncated = Boolean(body.preview_truncated);
        const rawMsgs = body.messages;
        const messages = Array.isArray(rawMsgs)
          ? rawMsgs.map((m) => {
              if (!m || typeof m !== "object") return { role: "unknown", excerpt: "" };
              const row = m as Record<string, unknown>;
              return { role: String(row.role ?? "unknown"), excerpt: String(row.excerpt ?? "") };
            })
          : [];
        setPreviewById((p) => ({
          ...p,
          [cid]: { status: "ready", title, message_count, preview_truncated, messages },
        }));
      } catch (e) {
        setPreviewById((p) => ({
          ...p,
          [cid]: {
            status: "error",
            message: e instanceof Error ? e.message : "Preview request failed",
          },
        }));
      }
    },
    [workspaceId, agentId],
  );

  const load = useCallback(
    async (refresh: boolean, runId?: number): Promise<CacheRow[]> => {
      setError(null);
      setListLoading(true);
      try {
        const q = refresh ? "?refresh=true" : "";
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/north/agents/${agentId}/conversations${q}`,
          { cache: "no-store" },
        );
        const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
        if (!res.ok) {
          if (runId === undefined || runId === runRef.current) {
            setError(readApiErrorMessage(body, `HTTP ${res.status}`));
          }
          return [];
        }
        if (refresh && (runId === undefined || runId === runRef.current)) {
          setExpandedId(null);
          setPreviewById({});
        }
        const items = (body.items as unknown[] | undefined) ?? [];
        const normalized: CacheRow[] = items
          .map((it) => normalizeConversationRow(it))
          .filter((r): r is CacheRow => r !== null && Boolean(r.north_conversation_id));
        if (runId === undefined || runId === runRef.current) {
          setRows(normalized);
        }
        return normalized;
      } finally {
        if (runId === undefined || runId === runRef.current) {
          setListLoading(false);
        }
      }
    },
    [workspaceId, agentId],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setStatsLoading(true);
      setStatsError(null);
      try {
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/north/agents/${agentId}/stats`,
          { cache: "no-store" },
        );
        const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
        if (cancelled) return;
        if (!res.ok) {
          setStatsError(readApiErrorMessage(body, `HTTP ${res.status}`));
          setStats(null);
          return;
        }
        setStats({
          imported_documents: Number(body.imported_documents ?? 0),
          derived_notes: Number(body.derived_notes ?? 0),
          cached_conversations: Number(body.cached_conversations ?? 0),
          note_amem_embeddings: Number(body.note_amem_embeddings ?? 0),
          import_digest: typeof body.import_digest === "string" ? body.import_digest : null,
        });
      } catch {
        if (!cancelled) setStatsError("Failed to load agent stats");
      } finally {
        if (!cancelled) setStatsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, agentId]);

  useEffect(() => {
    const id = ++runRef.current;
    void load(false, id);
    // Do not auto-call refresh when cache is empty: North may return an unscoped list and we would
    // attach unrelated conversations to this agent's cache. User explicitly uses "Refresh from North".
  }, [load]);

  useEffect(() => {
    if (!expandedId) return;
    const ent = previewById[expandedId];
    if (ent?.status === "ready" || ent?.status === "loading" || ent?.status === "error") return;
    void loadPreview(expandedId);
  }, [expandedId, previewById, loadPreview]);

  const toggleExpanded = (cid: string) => {
    setExpandedId((cur) => (cur === cid ? null : cid));
  };

  const importConv = async (cid: string) => {
    setBusy(cid);
    setError(null);
    setImportNotice(null);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/north/agents/${agentId}/conversations/${encodeURIComponent(cid)}/import`,
        { method: "POST" },
      );
      const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        setError(readApiErrorMessage(body, `Import HTTP ${res.status}`));
        return;
      }
      if (body.deduped === true) {
        setImportNotice("Already synced — ingestible content unchanged. No re-import needed.");
        void load(false);
        return;
      }
      const jid = body.job_id as string | null | undefined;
      const doc = body.document as { id?: string } | undefined;
      if (typeof jid === "string" && jid.length > 0) {
        registerActiveJob(jid, workspaceId, doc?.id ?? null, "document_parse");
        setImportNotice(
          "Import started — watch pipeline progress in the job drawer. When complete, find the transcript under Conversations.",
        );
        void load(false);
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <Link href="/agents" className="inline-flex items-center gap-1 text-caption text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" strokeWidth={1.5} aria-hidden />
        All agents
      </Link>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-h4 text-foreground">Agent conversations</h1>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-p text-muted-foreground",
            "hover:bg-secondary hover:text-foreground disabled:opacity-50",
          )}
          onClick={() => {
            setBusy("refresh");
            void load(true, undefined).finally(() => setBusy(null));
          }}
          disabled={busy === "refresh"}
        >
          <RefreshCw className="h-4 w-4" strokeWidth={1.5} aria-hidden />
          Refresh from North
        </button>
      </div>
      <div className="rounded-lg border border-border bg-secondary/60 px-3 py-3">
        {statsLoading ? (
          <p className="text-caption text-muted-foreground" role="status">
            Loading memory stats…
          </p>
        ) : statsError ? (
          <p className="text-caption text-red-300" role="alert">
            {statsError}
          </p>
        ) : stats ? (
          <div className="flex flex-wrap items-center gap-3 text-caption text-muted-foreground">
            <span>
              <strong className="text-foreground">{stats.imported_documents}</strong> imported
            </span>
            <span>
              <strong className="text-foreground">{stats.derived_notes}</strong> notes
            </span>
            <span>
              <strong className="text-foreground">{stats.cached_conversations}</strong> cached
            </span>
            <span>
              <strong className="text-foreground">{stats.note_amem_embeddings}</strong> A-MEM indexed
            </span>
            {stats.import_digest ? (
              <span
                className="font-mono text-muted-foreground"
                title="Rollup of imported conversation checksums for this agent"
              >
                digest {stats.import_digest.slice(0, 12)}…
              </span>
            ) : null}
            <Link
              href={`/notes?agentId=${encodeURIComponent(agentId)}`}
              className="rounded border border-border px-2 py-0.5 hover:bg-card hover:text-foreground"
            >
              View notes
            </Link>
            <Link
              href={`/graph?agent_id=${encodeURIComponent(agentId)}`}
              className="rounded border border-border px-2 py-0.5 hover:bg-card hover:text-foreground"
            >
              View graph
            </Link>
            <Link
              href={`/chat?agent_id=${encodeURIComponent(agentId)}`}
              className="rounded border border-border px-2 py-0.5 hover:bg-card hover:text-foreground"
            >
              Open in chat
            </Link>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 hover:bg-card hover:text-foreground disabled:opacity-50"
              disabled={dreamBusy}
              onClick={async () => {
                setDreamBusy(true);
                setError(null);
                try {
                  const res = await fetch(
                    `/api/v1/workspaces/${workspaceId}/north/agents/${agentId}/dream`,
                    { method: "POST" },
                  );
                  const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
                  if (!res.ok) {
                    setError(readApiErrorMessage(body, `Dream HTTP ${res.status}`));
                    return;
                  }
                  const jid = typeof body.job_id === "string" ? body.job_id : null;
                  if (jid) {
                    setDreamJobId(jid);
                    registerActiveJob(jid, workspaceId, null, "dreaming");
                    requestOpenLogConsole();
                  }
                } finally {
                  setDreamBusy(false);
                }
              }}
            >
              <Sparkles className="h-3.5 w-3.5" strokeWidth={1.5} aria-hidden />
              Dream
            </button>
          </div>
        ) : null}
      </div>
      <DreamJobStatus workspaceId={workspaceId} agentId={agentId} jobId={dreamJobId} />
      {error ? (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-p text-destructive">
          {error}
        </p>
      ) : null}
      {importNotice ? (
        <p className="rounded-md border border-border bg-secondary px-3 py-2 text-p text-muted-foreground">
          {importNotice}
        </p>
      ) : null}
      {listLoading && rows.length === 0 ? (
        <p className="text-caption text-muted-foreground" role="status">
          Loading conversations…
        </p>
      ) : null}
      <ul className="divide-y divide-border-subtle rounded-lg border border-border bg-card">
        {rows.map((r) => {
          const open = expandedId === r.north_conversation_id;
          const preview = previewById[r.north_conversation_id];
          const panelId = `conv-preview-${r.north_conversation_id}`;
          return (
            <li key={r.north_conversation_id} className="flex flex-col">
              <div className="flex items-start justify-between gap-3 px-3 py-2">
                <div className="flex min-w-0 flex-1 items-start gap-2">
                  <button
                    type="button"
                    className="mt-0.5 shrink-0 rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
                    aria-expanded={open}
                    aria-controls={panelId}
                    title={open ? "Collapse preview" : "Expand preview"}
                    onClick={() => toggleExpanded(r.north_conversation_id)}
                  >
                    {open ? (
                      <ChevronDown className="h-4 w-4" strokeWidth={1.5} aria-hidden />
                    ) : (
                      <ChevronRight className="h-4 w-4" strokeWidth={1.5} aria-hidden />
                    )}
                  </button>
                  <div className="min-w-0 flex-1">
                    {r.title ? (
                      <div className="truncate text-p text-foreground">{r.title}</div>
                    ) : null}
                    <p className="truncate font-mono text-caption text-muted-foreground">{r.north_conversation_id}</p>
                    <ConversationMemoryTelemetry
                      memory={
                        r.memory
                          ? {
                              ...r.memory,
                              outdated: r.sync_status === "outdated",
                            }
                          : null
                      }
                      notImported={
                        r.sync_status === "not_synced" && Boolean(r.memory?.cached || r.fetched_at)
                      }
                      importing={r.sync_status === "syncing"}
                    />
                  </div>
                </div>
                <ConversationAction
                  row={r}
                  agentId={agentId}
                  busy={busy === r.north_conversation_id}
                  onImport={() => void importConv(r.north_conversation_id)}
                />
              </div>
              {open ? (
                <div
                  id={panelId}
                  className="border-t border-border bg-secondary px-3 py-3 pl-10"
                  role="region"
                  aria-label="Conversation preview"
                >
                  {!preview || preview.status === "loading" ? (
                    <p className="text-caption text-muted-foreground" role="status">
                      Loading preview…
                    </p>
                  ) : null}
                  {preview?.status === "error" ? (
                    <div className="space-y-2">
                      <p className="text-caption text-destructive">{preview.message}</p>
                      <button
                        type="button"
                        className="rounded-md border border-border px-2 py-1 text-caption text-muted-foreground hover:bg-card hover:text-foreground"
                        onClick={() => void loadPreview(r.north_conversation_id)}
                      >
                        Retry preview
                      </button>
                    </div>
                  ) : null}
                  {preview?.status === "ready" ? (
                    <div className="flex max-h-[min(28rem,55vh)] flex-col gap-2 overflow-y-auto pr-1">
                      {(preview.title || preview.message_count > 0) && (
                        <div className="text-caption text-muted-foreground">
                          {preview.title ? <span className="text-muted-foreground">{preview.title}</span> : null}
                          {preview.title && preview.message_count > 0 ? " · " : null}
                          {preview.message_count > 0 ? (
                            <span>
                              {preview.message_count} message{preview.message_count === 1 ? "" : "s"}
                              {preview.preview_truncated ? " (preview shows first chunk only)" : ""}
                            </span>
                          ) : null}
                        </div>
                      )}
                      <div className="flex flex-col gap-2">
                        {preview.messages.map((m, i) => (
                          <div
                            key={`${r.north_conversation_id}-${i}-${m.role}`}
                            className={cn(
                              "rounded-md border border-border px-3 py-2",
                              m.role === "user" && "border-primary/25 bg-primary/5",
                              m.role === "assistant" && "bg-card",
                              m.role !== "user" && m.role !== "assistant" && "bg-card opacity-90",
                            )}
                          >
                            <div className="mb-1 text-caption font-medium uppercase tracking-wide text-muted-foreground">
                              {m.role}
                            </div>
                            {m.excerpt ? (
                              <pre className="whitespace-pre-wrap break-words font-regular text-p text-foreground">
                                {m.excerpt}
                              </pre>
                            ) : (
                              <p className="text-caption italic text-muted-foreground">No text content</p>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
      {rows.length === 0 && !error && !listLoading ? (
        <p className="text-caption text-muted-foreground">No cached conversations — click refresh to pull from North.</p>
      ) : null}
    </div>
  );
}
