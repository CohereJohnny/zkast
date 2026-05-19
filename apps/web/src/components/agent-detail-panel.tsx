"use client";

import { ArrowLeft, ChevronDown, ChevronRight, RefreshCw, Sparkles } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { DreamJobStatus } from "@/components/dream-job-status";
import { readApiErrorMessage } from "@/lib/api-error-message";
import { useJobEvents } from "@/lib/job-events";
import { cn } from "@/lib/utils";

type CacheRow = {
  north_conversation_id: string;
  fetched_at: string | null;
  title?: string | null;
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
    return { north_conversation_id: id, fetched_at: fetched, title };
  }
  const id = String(
    o.id ?? o.conversation_id ?? o.conversationId ?? o.thread_id ?? o.threadId ?? "",
  );
  if (!id) return null;
  const t = String(o.title ?? o.name ?? o.displayTitle ?? "").trim();
  return { north_conversation_id: id, fetched_at: null, title: t || null };
}

export function AgentDetailPanel({ workspaceId, agentId }: { workspaceId: string; agentId: string }) {
  const { registerActiveJob } = useJobEvents();
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
        setImportNotice("This conversation is already imported (same content checksum). Open Conversations to view status.");
        return;
      }
      const jid = body.job_id as string | null | undefined;
      const doc = body.document as { id?: string } | undefined;
      if (typeof jid === "string" && jid.length > 0) {
        registerActiveJob(jid, workspaceId, doc?.id ?? null, "document_parse");
        setImportNotice("Import started — watch pipeline progress in the job drawer. When complete, find the transcript under Conversations.");
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
      <div className="rounded-lg border border-border-subtle bg-surface-raised/60 px-3 py-3">
        {statsLoading ? (
          <p className="text-caption text-muted" role="status">
            Loading memory stats…
          </p>
        ) : statsError ? (
          <p className="text-caption text-red-300" role="alert">
            {statsError}
          </p>
        ) : stats ? (
          <div className="flex flex-wrap items-center gap-3 text-caption text-secondary">
            <span>
              <strong className="text-primary">{stats.imported_documents}</strong> imported
            </span>
            <span>
              <strong className="text-primary">{stats.derived_notes}</strong> notes
            </span>
            <span>
              <strong className="text-primary">{stats.cached_conversations}</strong> cached
            </span>
            <span>
              <strong className="text-primary">{stats.note_amem_embeddings}</strong> A-MEM indexed
            </span>
            <Link
              href={`/notes?agentId=${encodeURIComponent(agentId)}`}
              className="rounded border border-border-subtle px-2 py-0.5 hover:bg-surface hover:text-primary"
            >
              View notes
            </Link>
            <Link
              href={`/graph?agent_id=${encodeURIComponent(agentId)}`}
              className="rounded border border-border-subtle px-2 py-0.5 hover:bg-surface hover:text-primary"
            >
              View graph
            </Link>
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded border border-border-subtle px-2 py-0.5 hover:bg-surface hover:text-primary disabled:opacity-50"
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
                  if (jid) setDreamJobId(jid);
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
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-body text-destructive">
          {error}
        </p>
      ) : null}
      {importNotice ? (
        <p className="rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-body text-secondary">
          {importNotice}
        </p>
      ) : null}
      {listLoading && rows.length === 0 ? (
        <p className="text-caption text-muted" role="status">
          Loading conversations…
        </p>
      ) : null}
      <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle bg-surface">
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
                    className="mt-0.5 shrink-0 rounded p-1 text-muted hover:bg-surface-raised hover:text-primary"
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
                      <div className="truncate text-body text-primary">{r.title}</div>
                    ) : null}
                    <div className="truncate font-mono text-caption text-secondary">{r.north_conversation_id}</div>
                  </div>
                </div>
                <button
                  type="button"
                  className="shrink-0 rounded-md border border-border-subtle px-2 py-1 text-caption text-secondary hover:bg-surface-raised hover:text-primary disabled:opacity-50"
                  disabled={busy === r.north_conversation_id}
                  onClick={() => void importConv(r.north_conversation_id)}
                >
                  Import
                </button>
              </div>
              {open ? (
                <div
                  id={panelId}
                  className="border-t border-border-subtle bg-surface-raised px-3 py-3 pl-10"
                  role="region"
                  aria-label="Conversation preview"
                >
                  {!preview || preview.status === "loading" ? (
                    <p className="text-caption text-muted" role="status">
                      Loading preview…
                    </p>
                  ) : null}
                  {preview?.status === "error" ? (
                    <div className="space-y-2">
                      <p className="text-caption text-destructive">{preview.message}</p>
                      <button
                        type="button"
                        className="rounded-md border border-border-subtle px-2 py-1 text-caption text-secondary hover:bg-surface hover:text-primary"
                        onClick={() => void loadPreview(r.north_conversation_id)}
                      >
                        Retry preview
                      </button>
                    </div>
                  ) : null}
                  {preview?.status === "ready" ? (
                    <div className="flex max-h-[min(28rem,55vh)] flex-col gap-2 overflow-y-auto pr-1">
                      {(preview.title || preview.message_count > 0) && (
                        <div className="text-caption text-muted">
                          {preview.title ? <span className="text-secondary">{preview.title}</span> : null}
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
                              "rounded-md border border-border-subtle px-3 py-2",
                              m.role === "user" && "border-primary/25 bg-primary/5",
                              m.role === "assistant" && "bg-surface",
                              m.role !== "user" && m.role !== "assistant" && "bg-surface opacity-90",
                            )}
                          >
                            <div className="mb-1 text-caption font-medium uppercase tracking-wide text-muted">
                              {m.role}
                            </div>
                            {m.excerpt ? (
                              <pre className="whitespace-pre-wrap break-words font-sans text-body text-primary">
                                {m.excerpt}
                              </pre>
                            ) : (
                              <p className="text-caption italic text-muted">No text content</p>
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
        <p className="text-caption text-muted">No cached conversations — click refresh to pull from North.</p>
      ) : null}
    </div>
  );
}
