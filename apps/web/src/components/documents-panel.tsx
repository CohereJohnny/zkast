"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ConversationMemoryTelemetry,
  type ConversationMemoryStats,
} from "@/components/conversation-memory-telemetry";
import { DocumentDetailPanel } from "@/components/document-detail-panel";
import {
  DEFAULT_ONTOLOGY,
  OntologyPicker,
  type OntologyChoice,
} from "@/components/ontology-picker";
import { emitGraphInvalidated } from "@/lib/graph-events";
import { useActiveJobs, useJobEvents } from "@/lib/job-events";
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
  source_kind?: string;
  collection_id?: string | null;
  collection_name?: string | null;
  /** Present when listing ``north_conversation`` documents. */
  agent_id?: string | null;
  agent_display_name?: string;
  conversation_title?: string;
  north_conversation_id?: string | null;
  conversation_activity_at?: string | null;
  memory?: ConversationMemoryStats | null;
};

type CollectionRow = {
  id: string;
  name: string;
  document_count?: number;
};

const UPLOAD_ACCEPT =
  "application/pdf,.pdf,text/plain,.txt,text/markdown,.md,.markdown,message/rfc822,.eml";

function isAcceptedUpload(file: File): boolean {
  const name = file.name.toLowerCase();
  if (
    name.endsWith(".pdf") ||
    name.endsWith(".txt") ||
    name.endsWith(".md") ||
    name.endsWith(".markdown") ||
    name.endsWith(".eml")
  ) {
    return true;
  }
  const t = file.type;
  return (
    t === "application/pdf" ||
    t === "text/plain" ||
    t === "text/markdown" ||
    t === "text/x-markdown" ||
    t === "message/rfc822" ||
    t === "application/eml" ||
    t === ""
  );
}

function sourceKindBadge(kind: string | undefined): { label: string; className: string } {
  switch (kind) {
    case "text":
      return { label: "TXT", className: "bg-sky-500/15 text-sky-100" };
    case "markdown":
      return { label: "MD", className: "bg-emerald-500/15 text-emerald-100" };
    case "email":
      return { label: "EML", className: "bg-orange-500/15 text-orange-100" };
    default:
      return { label: "PDF", className: "bg-primary/15 text-foreground" };
  }
}

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
      return "bg-white/10 text-muted-foreground ring-1 ring-border-subtle";
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
  /** ``documents`` = file uploads; ``conversations`` = North agent transcript imports (same DB row shape). */
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
  const [uploadOntology, setUploadOntology] = useState<OntologyChoice>(DEFAULT_ONTOLOGY);
  const [collections, setCollections] = useState<CollectionRow[]>([]);
  const [uploadCollection, setUploadCollection] = useState("");
  const [filterCollectionId, setFilterCollectionId] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const activeJobsRef = useRef<Record<string, string>>({});

  const uploadLimit = maxBytes();

  activeJobsRef.current = activeJobs;

  const listSourceKind = library === "conversations" ? "north_conversation" : "uploads";

  const loadCollections = useCallback(async () => {
    if (library !== "documents") return;
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/document-collections`, {
        cache: "no-store",
      });
      const body = (await res.json().catch(() => ({}))) as { items?: CollectionRow[] };
      if (res.ok) setCollections(body.items ?? []);
    } catch {
      /* ignore */
    }
  }, [library, workspaceId]);

  const load = useCallback(async () => {
    setListError(null);
    try {
      const qs = new URLSearchParams({ source_kind: listSourceKind });
      if (library === "documents" && filterCollectionId) {
        qs.set("collection_id", filterCollectionId);
      }
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/documents?${qs.toString()}`,
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
  }, [workspaceId, listSourceKind, library, filterCollectionId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadCollections();
  }, [loadCollections]);

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

  const { registerActiveJob, requestOpenLogConsole, theaterFocusMode } = useJobEvents();
  const activeJobCount = useActiveJobs().length;
  const theaterFocus = theaterFocusMode && activeJobCount > 0;

  const registerJob = useCallback(
    (docId: string, jobId: string) => {
      setActiveJobs((m) => ({ ...m, [docId]: jobId }));
      registerActiveJob(jobId, workspaceId, docId, "document_parse");
      requestOpenLogConsole();
    },
    [registerActiveJob, requestOpenLogConsole, workspaceId],
  );

  /** Re-attach SSE when the tab was refreshed mid-ingestion (localStorage may lack the job). */
  useEffect(() => {
    if (!hasActiveIngestion) return;
    let cancelled = false;
    const sync = async () => {
      try {
        const res = await fetch(
          `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/jobs/overview`,
          { cache: "no-store" },
        );
        if (!res.ok || cancelled) return;
        const body = (await res.json()) as {
          pipeline_jobs?: Array<{
            job_id?: string;
            document_id?: string;
            status?: string;
            kind?: string;
          }>;
        };
        for (const j of body.pipeline_jobs ?? []) {
          if (!j.job_id || !j.document_id) continue;
          const st = (j.status ?? "").toLowerCase();
          if (st === "succeeded" || st === "failed" || st === "cancelled") continue;
          registerActiveJob(
            j.job_id,
            workspaceId,
            j.document_id,
            (j.kind as "document_parse" | undefined) ?? "document_parse",
          );
          setActiveJobs((m) => ({ ...m, [j.document_id!]: j.job_id! }));
        }
      } catch {
        /* ignore */
      }
    };
    void sync();
    const t = window.setInterval(() => void sync(), 8000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [hasActiveIngestion, registerActiveJob, workspaceId]);

  const uploadFiles = async (files: File[]) => {
    setUploadError(null);
    const fd = new FormData();
    for (const f of files) {
      if (f.size > uploadLimit) {
        setUploadError(`"${f.name}" exceeds maximum upload size`);
        return;
      }
      if (!isAcceptedUpload(f)) {
        setUploadError(`"${f.name}" is not an accepted type (PDF, TXT, MD, EML)`);
        return;
      }
      fd.append("file", f);
    }
    fd.append("ontology_name", uploadOntology.name);
    fd.append("ontology_version", uploadOntology.version);
    const coll = uploadCollection.trim();
    if (coll) {
      const existing = collections.find(
        (c) => c.name.toLowerCase() === coll.toLowerCase() || c.id === coll,
      );
      if (existing) {
        fd.append("collection_id", existing.id);
      } else {
        fd.append("collection_name", coll);
      }
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
      : theaterFocus
        ? "rounded-md border border-dashed px-3 py-2"
        : "rounded-lg border border-dashed px-3 py-2.5";

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
    <div
      className={cn(
        variant === "full" ? "flex flex-col gap-6" : "flex flex-col gap-3",
        variant !== "full" && !theaterFocus && "h-full",
      )}
    >
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
        <section aria-label="Upload documents" className={theaterFocus ? "shrink-0" : undefined}>
          {!theaterFocus ? (
            <div className="flex flex-wrap items-end justify-between gap-3">
              <p className="text-h5 text-muted-foreground">{listHeading}</p>
              <div className="flex flex-wrap items-end gap-3">
                <label className="text-caption text-muted-foreground">
                  Collection
                  <input
                    list={`doc-collections-${workspaceId}`}
                    value={uploadCollection}
                    onChange={(e) => setUploadCollection(e.target.value)}
                    placeholder="Optional name"
                    className="mt-1 block min-w-[10rem] rounded border border-input bg-card px-2 py-1 text-muted-foreground"
                  />
                  <datalist id={`doc-collections-${workspaceId}`}>
                    {collections.map((c) => (
                      <option key={c.id} value={c.name} />
                    ))}
                  </datalist>
                </label>
                <OntologyPicker
                  workspaceId={workspaceId}
                  value={uploadOntology}
                  onChange={setUploadOntology}
                  className="min-w-[12rem]"
                  compact
                />
                <button
                  type="button"
                  className="rounded-md bg-primary px-3 py-1.5 text-p font-medium text-primary-foreground"
                  onClick={() => inputRef.current?.click()}
                >
                  Choose files
                </button>
              </div>
            </div>
          ) : (
            <div className="mb-2 flex flex-wrap items-end gap-2">
              <input
                list={`doc-collections-theater-${workspaceId}`}
                value={uploadCollection}
                onChange={(e) => setUploadCollection(e.target.value)}
                placeholder="Collection (optional)"
                className="min-w-[8rem] flex-1 rounded border border-input bg-card px-2 py-1 text-caption text-muted-foreground"
              />
              <datalist id={`doc-collections-theater-${workspaceId}`}>
                {collections.map((c) => (
                  <option key={c.id} value={c.name} />
                ))}
              </datalist>
              <OntologyPicker
                workspaceId={workspaceId}
                value={uploadOntology}
                onChange={setUploadOntology}
                className="min-w-[10rem] flex-1"
                compact
              />
            </div>
          )}
          <input
            ref={inputRef}
            type="file"
            accept={UPLOAD_ACCEPT}
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
            className={cn(
              dropZoneClass,
              "flex cursor-pointer items-center justify-between gap-2 text-caption outline-none transition-colors",
              theaterFocus ? "mt-0" : "mt-3 flex-col justify-center text-center",
              dragOver ? "border-primary bg-primary/10" : "border-input bg-card/60",
            )}
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
            <span className="text-p text-muted-foreground">
              {theaterFocus
                ? "Drop PDF/TXT/MD/EML or browse"
                : "Drop PDF, TXT, MD, or EML files here or click to browse"}
            </span>
            <span className="shrink-0 text-caption text-muted-foreground">
              {theaterFocus ? (
                <span className="rounded border border-border px-2 py-0.5">Choose</span>
              ) : (
                <>Max {Math.round(uploadLimit / (1024 * 1024))} MB per file</>
              )}
            </span>
          </div>
          {uploadError ? (
            <p className="mt-2 text-caption text-red-300" role="alert">
              {uploadError}
            </p>
          ) : null}
          {!theaterFocus && collections.length > 0 ? (
            <label className="mt-3 block text-caption text-muted-foreground">
              Filter by collection
              <select
                className="mt-1 w-full max-w-xs cursor-pointer rounded border border-input bg-card px-2 py-1 text-muted-foreground"
                value={filterCollectionId}
                onChange={(e) => setFilterCollectionId(e.target.value)}
              >
                <option value="">All uploads</option>
                {collections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                    {typeof c.document_count === "number" ? ` (${c.document_count})` : ""}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </section>
      ) : (
        <section aria-label="Imported conversations">
          <p className="text-h5 text-muted-foreground">{listHeading}</p>
          <p className="mt-2 text-caption text-muted-foreground">
            Transcripts imported from{" "}
            <Link href="/agents" className="text-muted-foreground underline hover:text-foreground">
              Agents
            </Link>{" "}
            appear here. PDFs stay under Documents.
          </p>
        </section>
      )}

      {!theaterFocus ? (
      <section aria-label="Document list" className="min-h-0 flex-1 overflow-auto">
        {loading ? (
          <p className="text-caption text-muted-foreground">
            {library === "conversations" ? "Loading conversations…" : "Loading documents…"}
          </p>
        ) : listError ? (
          <p className="text-caption text-red-300" role="alert">
            {listError}
          </p>
        ) : docs.length === 0 ? (
          <p className="text-caption text-muted-foreground">
            {library === "conversations"
              ? "No imported conversations yet. Open an agent under Agents and import from North."
              : "No documents uploaded yet."}
          </p>
        ) : library === "conversations" ? (
          <div className="flex flex-col gap-6">
            {conversationSections.map((sec) => {
              const expanded = !collapsedAgentSections.has(sec.key);
              return (
                <section
                  key={sec.key}
                  className="overflow-hidden rounded-lg border border-border bg-card/40"
                  aria-label={`Conversations — ${sec.label}`}
                >
                  <button
                    type="button"
                    className={cn(
                      "flex w-full items-start gap-2 bg-card/80 px-3 py-2.5 text-left transition-colors hover:bg-card/95",
                      expanded ? "border-b border-border" : "",
                    )}
                    aria-expanded={expanded}
                    onClick={() => toggleAgentSectionCollapsed(sec.key)}
                  >
                    <ChevronRight
                      className={cn(
                        "mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200",
                        expanded && "rotate-90",
                      )}
                      strokeWidth={1.5}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-p font-semibold text-foreground">{sec.label}</span>
                      <span className="mt-0.5 block text-caption text-muted-foreground">
                        {sec.rows.length} imported conversation{sec.rows.length === 1 ? "" : "s"}
                      </span>
                    </span>
                  </button>
                  {expanded ? (
                    <ul className="ml-4 border-l-2 border-border pl-3 pr-2">
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
                          <li key={d.id} className="border-b border-border last:border-b-0">
                            <button
                              type="button"
                              className="flex w-full flex-col gap-1 py-3 pl-1 pr-1 text-left hover:bg-card/70"
                              onClick={() => setSelectedId(d.id)}
                            >
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="line-clamp-2 text-p font-medium text-muted-foreground">{title}</span>
                                <span
                                  className={`shrink-0 rounded-full px-2 py-0.5 text-caption capitalize ${statusStyles(d.status)}`}
                                >
                                  {d.status.replace(/_/g, " ")}
                                </span>
                              </div>
                              <p className="text-caption text-muted-foreground">
                                <span className="text-muted-foreground/90">{whenLabel}: </span>
                                {formatLocalTs(whenIso)}
                                {d.page_count != null ? (
                                  <span className="text-muted-foreground">
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
                                  className="truncate font-mono text-[11px] text-muted-foreground/80"
                                  title={d.north_conversation_id}
                                >
                                  {d.north_conversation_id}
                                </p>
                              ) : null}
                              {showBar ? (
                                <div className="h-1.5 w-full overflow-hidden rounded bg-white/10" aria-hidden>
                                  <div
                                    className="h-full bg-primary transition-[width] duration-300"
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
          <ul className="divide-y divide-border-subtle rounded-lg border border-border bg-card/40">
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
                    className="flex w-full flex-col gap-1 px-3 py-3 text-left hover:bg-card/80"
                    onClick={() => setSelectedId(d.id)}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="flex min-w-0 flex-1 items-center gap-2">
                        <span
                          className={`shrink-0 rounded px-1 py-0.5 text-[9px] font-medium uppercase tracking-wide ${sourceKindBadge(d.source_kind).className}`}
                        >
                          {sourceKindBadge(d.source_kind).label}
                        </span>
                        <span className="truncate text-p font-medium text-muted-foreground">
                          {d.original_filename}
                        </span>
                        {d.collection_name ? (
                          <span className="shrink-0 rounded bg-teal-500/15 px-1.5 py-0.5 text-[10px] text-teal-100">
                            {d.collection_name}
                          </span>
                        ) : null}
                      </span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-caption capitalize ${statusStyles(d.status)}`}
                      >
                        {d.status.replace(/_/g, " ")}
                      </span>
                      {d.page_count != null ? (
                        <span className="text-caption text-muted-foreground">{d.page_count} pages</span>
                      ) : null}
                    </div>
                    {showBar ? (
                      <div className="h-1.5 w-full overflow-hidden rounded bg-white/10" aria-hidden>
                        <div
                          className="h-full bg-primary transition-[width] duration-300"
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
      ) : null}

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
