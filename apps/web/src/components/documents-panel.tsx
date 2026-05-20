"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ConversationMemoryTelemetry,
  type ConversationMemoryStats,
} from "@/components/conversation-memory-telemetry";
import { DocumentDetailPanel } from "@/components/document-detail-panel";
import { emitGraphInvalidated } from "@/lib/graph-events";
import { useJobEvents } from "@/lib/job-events";
import { cn } from "@/lib/utils";

/** Document rows in these states advance in the worker; poll the list so UI stays in sync with the DB. */
const INGESTION_ACTIVE_STATUSES = new Set([
  "queued",
  "parsing",
  "generating_notes",
  "extracting_graph",
  "building_graph",
]);

type DocRow = {
  id: string;
  original_filename: string;
  byte_size: number;
  page_count: number | null;
  status: string;
  failure_reason: string | null;
  created_at: string;
  /** Present when listing ``north_conversation`` documents. */
  agent_id?: string | null;
  agent_display_name?: string;
  conversation_title?: string;
  north_conversation_id?: string | null;
  conversation_activity_at?: string | null;
  memory?: ConversationMemoryStats | null;
};

function formatLocalTs(iso: string | undefined | null): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Date(t).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function maxBytes(): number {
  return 52428800;
}

function JobStreamBridge({
  docId,
  jobId,
  workspaceId,
  onTerminal,
  onProgress,
}: {
  docId: string;
  jobId: string;
  workspaceId: string;
  onTerminal: () => void;
  onProgress: (docId: string, pct: number | null) => void;
}) {
  const termRef = useRef(onTerminal);
  const progRef = useRef(onProgress);
  termRef.current = onTerminal;
  progRef.current = onProgress;

  useEffect(() => {
    const url = `/api/v1/jobs/${encodeURIComponent(jobId)}/events?workspaceId=${encodeURIComponent(workspaceId)}`;
    const es = new EventSource(url);
    es.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as { type: string; percent?: number };
        if (typeof msg.percent === "number") {
          progRef.current(docId, msg.percent);
        }
        if (msg.type === "job_completed") {
          progRef.current(docId, 100);
          es.close();
          termRef.current();
        }
        if (msg.type === "job_failed") {
          progRef.current(docId, null);
          es.close();
          termRef.current();
        }
      } catch {
        /* ignore malformed */
      }
    };
    es.onerror = () => {
      es.close();
    };
    return () => es.close();
  }, [docId, jobId, workspaceId]);
  return null;
}

function statusStyles(status: string): string {
  switch (status) {
    case "ready":
      return "bg-emerald-500/15 text-emerald-200 ring-1 ring-emerald-500/40";
    case "failed":
      return "bg-red-500/15 text-red-200 ring-1 ring-red-500/40";
    case "parsing":
    case "queued":
    case "generating_notes":
    case "extracting_graph":
    case "building_graph":
      return "bg-amber-500/15 text-amber-100 ring-1 ring-amber-500/35";
    default:
      return "bg-white/10 text-muted ring-1 ring-border-subtle";
  }
}

/** When no live SSE % for this doc, approximate bar width from DB pipeline stage (distinct per stage). */
function ingestionProgressFallbackPct(status: string): number {
  switch (status) {
    case "queued":
      return 14;
    case "parsing":
      return 30;
    case "generating_notes":
      return 48;
    case "extracting_graph":
      return 68;
    case "building_graph":
      return 86;
    default:
      return 12;
  }
}

export function DocumentsPanel({
  workspaceId,
  variant = "compact",
  library = "documents",
}: {
  workspaceId: string;
  variant?: "compact" | "full";
  /** ``documents`` = PDF uploads; ``conversations`` = North agent transcript imports (same DB row shape). */
  library?: "documents" | "conversations";
}) {
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [activeJobs, setActiveJobs] = useState<Record<string, string>>({});
  const [progressByDoc, setProgressByDoc] = useState<Record<string, number>>({});
  const [dragOver, setDragOver] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [listRefreshNonce, setListRefreshNonce] = useState(0);
  const [collapsedAgentSections, setCollapsedAgentSections] = useState<Set<string>>(() => new Set());
  const inputRef = useRef<HTMLInputElement>(null);
  const activeJobsRef = useRef<Record<string, string>>({});

  const uploadLimit = maxBytes();

  activeJobsRef.current = activeJobs;

  const listSourceKind = library === "conversations" ? "north_conversation" : "pdf";

  const load = useCallback(async () => {
    setListError(null);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/documents?source_kind=${listSourceKind}`,
        { cache: "no-store" },
      );
      const body = (await res.json()) as { items?: DocRow[]; error?: { message?: string } };
      if (!res.ok) {
        setListError(body.error?.message ?? "Failed to load documents");
        return;
      }
      const items = body.items ?? [];
      setDocs(items);
      setListRefreshNonce((n) => n + 1);
      setProgressByDoc((prev) => {
        const jobs = activeJobsRef.current;
        const next = { ...prev };
        for (const id of Object.keys(next)) {
          if (!jobs[id]) delete next[id];
        }
        return next;
      });
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, listSourceKind]);

  useEffect(() => {
    void load();
  }, [load]);

  const hasActiveIngestion = useMemo(
    () => docs.some((d) => INGESTION_ACTIVE_STATUSES.has(d.status)),
    [docs],
  );

  useEffect(() => {
    if (!hasActiveIngestion) return;
    const t = window.setInterval(() => void load(), 4000);
    return () => window.clearInterval(t);
  }, [hasActiveIngestion, load]);

  const onProgress = useCallback((docId: string, pct: number | null) => {
    setProgressByDoc((prev) => {
      const n = { ...prev };
      if (pct === null) {
        delete n[docId];
      } else {
        n[docId] = pct;
      }
      return n;
    });
  }, []);

  const clearJob = useCallback((docId: string) => {
    setActiveJobs((m) => {
      const n = { ...m };
      delete n[docId];
      return n;
    });
    setProgressByDoc((p) => {
      const n = { ...p };
      delete n[docId];
      return n;
    });
  }, []);

  const finishJob = useCallback(
    (docId: string) => {
      clearJob(docId);
      void load();
      emitGraphInvalidated();
    },
    [clearJob, load],
  );

  const { registerActiveJob } = useJobEvents();

  const registerJob = useCallback(
    (docId: string, jobId: string) => {
      setActiveJobs((m) => ({ ...m, [docId]: jobId }));
      registerActiveJob(jobId, workspaceId, docId, "document_parse");
    },
    [registerActiveJob, workspaceId],
  );

  const uploadFiles = async (files: File[]) => {
    setUploadError(null);
    const fd = new FormData();
    for (const f of files) {
      if (f.size > uploadLimit) {
        setUploadError(`"${f.name}" exceeds maximum upload size`);
        return;
      }
      const okType = f.type === "application/pdf" || f.type === "" || f.name.toLowerCase().endsWith(".pdf");
      if (!okType) {
        setUploadError(`"${f.name}" is not a PDF`);
        return;
      }
      fd.append("file", f);
    }

    const res = await fetch(`/api/v1/workspaces/${workspaceId}/documents`, {
      method: "POST",
      body: fd,
    });
    const raw = await res.text();
    if (!res.ok) {
      try {
        const j = JSON.parse(raw) as { error?: { message?: string } };
        setUploadError(j.error?.message ?? `Upload failed (${res.status})`);
      } catch {
        setUploadError(`Upload failed (${res.status})`);
      }
      return;
    }

    try {
      const body = JSON.parse(raw) as {
        documents: Array<DocRow & { job_id?: string }>;
        job_ids: string[];
      };
      const mapping: Record<string, string> = {};
      body.documents.forEach((d, i) => {
        const jid = d.job_id ?? body.job_ids[i];
        if (jid) {
          mapping[d.id] = jid;
          registerActiveJob(jid, workspaceId, d.id, "document_parse");
        }
      });
      setActiveJobs((m) => ({ ...m, ...mapping }));
      await load();
    } catch {
      setUploadError("Unexpected response from server");
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) void uploadFiles(files);
  };

  const dropZoneClass =
    variant === "full"
      ? "min-h-[180px] rounded-lg border-2 border-dashed px-6 py-10"
      : "min-h-[120px] rounded-lg border border-dashed px-4 py-6";

  const selected = docs.find((d) => d.id === selectedId) ?? null;

  const conversationSections = useMemo(() => {
    if (library !== "conversations") return [];
    const map = new Map<string, { key: string; label: string; rows: DocRow[] }>();
    for (const d of docs) {
      const key =
        typeof d.agent_id === "string" && d.agent_id.length > 0
          ? `agent:${d.agent_id}`
          : `name:${(d.agent_display_name ?? "unknown").toLowerCase()}`;
      const label = d.agent_display_name ?? "Unknown agent";
      let g = map.get(key);
      if (!g) {
        g = { key, label, rows: [] };
        map.set(key, g);
      }
      g.rows.push(d);
    }
    const sections = Array.from(map.values()).sort((a, b) =>
      a.label.localeCompare(b.label, undefined, { sensitivity: "base" }),
    );
    for (const s of sections) {
      s.rows.sort((a: DocRow, b: DocRow) => {
        const ta = Date.parse(a.conversation_activity_at ?? a.created_at);
        const tb = Date.parse(b.conversation_activity_at ?? b.created_at);
        return (Number.isNaN(tb) ? 0 : tb) - (Number.isNaN(ta) ? 0 : ta);
      });
    }
    return sections;
  }, [docs, library]);

  const toggleAgentSectionCollapsed = useCallback((key: string) => {
    setCollapsedAgentSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const isPdfLibrary = library === "documents";
  const listHeading =
    library === "conversations"
      ? variant === "full"
        ? "Imported conversations"
        : "Conversations"
      : variant === "full"
        ? "Documents"
        : "Documents";

  return (
    <div className={variant === "full" ? "flex flex-col gap-6" : "flex h-full flex-col gap-3"}>
      {Object.entries(activeJobs).map(([docId, jobId]) => (
        <JobStreamBridge
          key={`${docId}-${jobId}`}
          docId={docId}
          jobId={jobId}
          workspaceId={workspaceId}
          onTerminal={() => finishJob(docId)}
          onProgress={onProgress}
        />
      ))}

      {isPdfLibrary ? (
        <section aria-label="Upload PDFs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-title-3 text-secondary">{listHeading}</p>
            <button
              type="button"
              className="rounded-md bg-accent-primary px-3 py-1.5 text-body font-medium text-canvas"
              onClick={() => inputRef.current?.click()}
            >
              Choose PDFs
            </button>
          </div>
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf,.pdf"
            multiple
            className="sr-only"
            onChange={(e) => {
              const files = e.target.files ? Array.from(e.target.files) : [];
              e.target.value = "";
              if (files.length) void uploadFiles(files);
            }}
          />
          <div
            role="button"
            tabIndex={0}
            className={`${dropZoneClass} mt-3 flex cursor-pointer flex-col items-center justify-center gap-2 text-center text-caption outline-none transition-colors ${
              dragOver ? "border-accent-primary bg-accent-primary/10" : "border-border-strong bg-surface/60"
            }`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                inputRef.current?.click();
              }
            }}
            onClick={() => inputRef.current?.click()}
          >
            <span className="text-body text-secondary">Drop PDFs here or click to browse</span>
            <span className="text-caption text-muted">Max {Math.round(uploadLimit / (1024 * 1024))} MB per file</span>
          </div>
          {uploadError ? (
            <p className="mt-2 text-caption text-red-300" role="alert">
              {uploadError}
            </p>
          ) : null}
        </section>
      ) : (
        <section aria-label="Imported conversations">
          <p className="text-title-3 text-secondary">{listHeading}</p>
          <p className="mt-2 text-caption text-muted">
            Transcripts imported from{" "}
            <Link href="/agents" className="text-secondary underline hover:text-primary">
              Agents
            </Link>{" "}
            appear here. PDFs stay under Documents.
          </p>
        </section>
      )}

      <section aria-label="Document list" className="min-h-0 flex-1 overflow-auto">
        {loading ? (
          <p className="text-caption text-muted">
            {library === "conversations" ? "Loading conversations…" : "Loading documents…"}
          </p>
        ) : listError ? (
          <p className="text-caption text-red-300" role="alert">
            {listError}
          </p>
        ) : docs.length === 0 ? (
          <p className="text-caption text-muted">
            {library === "conversations"
              ? "No imported conversations yet. Open an agent under Agents and import from North."
              : "No PDFs uploaded yet."}
          </p>
        ) : library === "conversations" ? (
          <div className="flex flex-col gap-6">
            {conversationSections.map((sec) => {
              const expanded = !collapsedAgentSections.has(sec.key);
              return (
                <section
                  key={sec.key}
                  className="overflow-hidden rounded-lg border border-border-subtle bg-surface/40"
                  aria-label={`Conversations — ${sec.label}`}
                >
                  <button
                    type="button"
                    className={cn(
                      "flex w-full items-start gap-2 bg-surface/80 px-3 py-2.5 text-left transition-colors hover:bg-surface/95",
                      expanded ? "border-b border-border-subtle" : "",
                    )}
                    aria-expanded={expanded}
                    onClick={() => toggleAgentSectionCollapsed(sec.key)}
                  >
                    <ChevronRight
                      className={cn(
                        "mt-0.5 h-4 w-4 shrink-0 text-muted transition-transform duration-200",
                        expanded && "rotate-90",
                      )}
                      strokeWidth={1.5}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-body font-semibold text-primary">{sec.label}</span>
                      <span className="mt-0.5 block text-caption text-muted">
                        {sec.rows.length} imported conversation{sec.rows.length === 1 ? "" : "s"}
                      </span>
                    </span>
                  </button>
                  {expanded ? (
                    <ul className="ml-4 border-l-2 border-border-subtle pl-3 pr-2">
                      {sec.rows.map((d: DocRow) => {
                        const jobId = activeJobs[d.id];
                        const livePct = progressByDoc[d.id];
                        const stageFallback = ingestionProgressFallbackPct(d.status);
                        const barPct =
                          jobId && typeof livePct === "number"
                            ? Math.min(100, Math.max(8, livePct))
                            : Math.min(100, Math.max(8, d.status === "ready" ? 100 : stageFallback));
                        const showBar =
                          Boolean(jobId) ||
                          d.status === "queued" ||
                          d.status === "parsing" ||
                          d.status === "generating_notes" ||
                          d.status === "extracting_graph" ||
                          d.status === "building_graph";
                        const title =
                          (d.conversation_title && d.conversation_title.trim()) || d.original_filename;
                        const whenIso = d.conversation_activity_at ?? d.created_at;
                        const whenLabel = d.conversation_activity_at ? "Conversation" : "Imported";
                        return (
                          <li key={d.id} className="border-b border-border-subtle last:border-b-0">
                            <button
                              type="button"
                              className="flex w-full flex-col gap-1 py-3 pl-1 pr-1 text-left hover:bg-surface/70"
                              onClick={() => setSelectedId(d.id)}
                            >
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="line-clamp-2 text-body font-medium text-secondary">{title}</span>
                                <span
                                  className={`shrink-0 rounded-full px-2 py-0.5 text-caption capitalize ${statusStyles(d.status)}`}
                                >
                                  {d.status.replace(/_/g, " ")}
                                </span>
                              </div>
                              <p className="text-caption text-muted">
                                <span className="text-secondary/90">{whenLabel}: </span>
                                {formatLocalTs(whenIso)}
                                {d.page_count != null ? (
                                  <span className="text-muted">
                                    {" "}
                                    · {d.page_count} episode{d.page_count === 1 ? "" : "s"}
                                  </span>
                                ) : null}
                              </p>
                              <ConversationMemoryTelemetry
                                memory={d.memory}
                                documentStatus={d.status}
                                importing={INGESTION_ACTIVE_STATUSES.has(d.status)}
                              />
                              {d.north_conversation_id ? (
                                <p
                                  className="truncate font-mono text-[11px] text-muted/80"
                                  title={d.north_conversation_id}
                                >
                                  {d.north_conversation_id}
                                </p>
                              ) : null}
                              {showBar ? (
                                <div className="h-1.5 w-full overflow-hidden rounded bg-white/10" aria-hidden>
                                  <div
                                    className="h-full bg-accent-primary transition-[width] duration-300"
                                    style={{ width: `${barPct}%` }}
                                  />
                                </div>
                              ) : null}
                              {d.failure_reason ? (
                                <p className="text-caption text-red-300">{d.failure_reason}</p>
                              ) : null}
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  ) : null}
                </section>
              );
            })}
          </div>
        ) : (
          <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle bg-surface/40">
            {docs.map((d) => {
              const jobId = activeJobs[d.id];
              const livePct = progressByDoc[d.id];
              const stageFallback = ingestionProgressFallbackPct(d.status);
              const barPct =
                jobId && typeof livePct === "number"
                  ? Math.min(100, Math.max(8, livePct))
                  : Math.min(100, Math.max(8, d.status === "ready" ? 100 : stageFallback));
              const showBar =
                Boolean(jobId) ||
                d.status === "queued" ||
                d.status === "parsing" ||
                d.status === "generating_notes" ||
                d.status === "extracting_graph" ||
                d.status === "building_graph";
              return (
                <li key={d.id}>
                  <button
                    type="button"
                    className="flex w-full flex-col gap-1 px-3 py-3 text-left hover:bg-surface/80"
                    onClick={() => setSelectedId(d.id)}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-body font-medium text-secondary">{d.original_filename}</span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-caption capitalize ${statusStyles(d.status)}`}
                      >
                        {d.status.replace(/_/g, " ")}
                      </span>
                      {d.page_count != null ? (
                        <span className="text-caption text-muted">{d.page_count} pages</span>
                      ) : null}
                    </div>
                    {showBar ? (
                      <div className="h-1.5 w-full overflow-hidden rounded bg-white/10" aria-hidden>
                        <div
                          className="h-full bg-accent-primary transition-[width] duration-300"
                          style={{ width: `${barPct}%` }}
                        />
                      </div>
                    ) : null}
                    {d.failure_reason ? (
                      <p className="text-caption text-red-300">{d.failure_reason}</p>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {variant === "full" && selected ? (
        <DocumentDetailPanel
          workspaceId={workspaceId}
          documentId={selected.id}
          listRefreshNonce={listRefreshNonce}
          onClose={() => setSelectedId(null)}
          onDeleted={() => {
            setSelectedId(null);
            void load();
          }}
          onJobStarted={registerJob}
        />
      ) : null}
    </div>
  );
}
