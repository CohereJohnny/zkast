"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type DocRow = {
  id: string;
  original_filename: string;
  byte_size: number;
  page_count: number | null;
  status: string;
  failure_reason: string | null;
  created_at: string;
};

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
      return "bg-amber-500/15 text-amber-100 ring-1 ring-amber-500/35";
    default:
      return "bg-white/10 text-muted ring-1 ring-border-subtle";
  }
}

export function DocumentsPanel({
  workspaceId,
  variant = "compact",
}: {
  workspaceId: string;
  variant?: "compact" | "full";
}) {
  const [docs, setDocs] = useState<DocRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [activeJobs, setActiveJobs] = useState<Record<string, string>>({});
  const [progressByDoc, setProgressByDoc] = useState<Record<string, number>>({});
  const [dragOver, setDragOver] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadLimit = maxBytes();

  const load = useCallback(async () => {
    setListError(null);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/documents`, { cache: "no-store" });
      const body = (await res.json()) as { items?: DocRow[]; error?: { message?: string } };
      if (!res.ok) {
        setListError(body.error?.message ?? "Failed to load documents");
        return;
      }
      setDocs(body.items ?? []);
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

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
    },
    [clearJob, load],
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
        if (jid) mapping[d.id] = jid;
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

      <section aria-label="Upload PDFs">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-title-3 text-secondary">
            {variant === "full" ? "Documents" : "Documents"}
          </p>
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

      <section aria-label="Document list" className="min-h-0 flex-1 overflow-auto">
        {loading ? (
          <p className="text-caption text-muted">Loading documents…</p>
        ) : listError ? (
          <p className="text-caption text-red-300" role="alert">
            {listError}
          </p>
        ) : docs.length === 0 ? (
          <p className="text-caption text-muted">No PDFs uploaded yet.</p>
        ) : (
          <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle bg-surface/40">
            {docs.map((d) => {
              const jobId = activeJobs[d.id];
              const pct = progressByDoc[d.id];
              const showBar = Boolean(jobId) || d.status === "queued" || d.status === "parsing";
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
                          style={{ width: `${Math.min(100, Math.max(8, pct ?? (d.status === "ready" ? 100 : 12)))}%` }}
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
        <aside
          className="fixed inset-y-0 right-0 z-40 w-full max-w-md border-l border-border-strong bg-canvas p-4 shadow-xl"
          aria-label="Document details"
        >
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-title-3 text-secondary">{selected.original_filename}</p>
              <p className="mt-1 text-caption text-muted">
                {selected.page_count != null ? `${selected.page_count} pages · ` : ""}
                {(selected.byte_size / 1024).toFixed(1)} KB
              </p>
            </div>
            <button
              type="button"
              className="rounded-md border border-border-strong px-2 py-1 text-caption text-muted hover:bg-surface"
              onClick={() => setSelectedId(null)}
            >
              Close
            </button>
          </div>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              className="rounded-md bg-red-500/80 px-3 py-1.5 text-caption font-medium text-white"
              onClick={async () => {
                const ok = window.confirm("Delete this document and its episodes?");
                if (!ok) return;
                const res = await fetch(`/api/v1/workspaces/${workspaceId}/documents/${selected.id}`, {
                  method: "DELETE",
                });
                if (res.ok) {
                  setSelectedId(null);
                  await load();
                }
              }}
            >
              Delete document
            </button>
          </div>
          <p className="mt-6 text-caption text-muted">
            Full ingestion timeline and graph linkage ship in later sprints.
          </p>
        </aside>
      ) : null}
    </div>
  );
}
