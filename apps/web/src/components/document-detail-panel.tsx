"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/feedback-provider";
import { emitGraphInvalidated } from "@/lib/graph-events";

type IngestionRun = {
  id: string;
  started_at: string;
  ended_at: string | null;
  status: string;
  pipeline_version: string;
  stats: unknown;
};

type DocDetail = {
  id: string;
  original_filename: string;
  mime_type: string;
  byte_size: number;
  page_count: number | null;
  status: string;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
};

type DeletePreview = {
  exclusive_note_count: number;
  shared_note_count: number;
  entity_touch_count: number;
  relationship_touch_count: number;
};

/** Next routes may return `{ error }`; proxied FastAPI uses `{ detail: string | { error?: { message } } }`. */
function messageFromApiJson(raw: string): string | null {
  try {
    const j = JSON.parse(raw) as Record<string, unknown>;
    const topErr = j.error;
    if (typeof topErr === "object" && topErr !== null && "message" in topErr) {
      const m = (topErr as { message?: unknown }).message;
      if (typeof m === "string" && m.trim()) return m;
    }
    const det = j.detail;
    if (typeof det === "string" && det.trim()) return det;
    if (typeof det === "object" && det !== null) {
      const d = det as Record<string, unknown>;
      const inner = d.error;
      if (typeof inner === "object" && inner !== null && "message" in inner) {
        const m = (inner as { message?: unknown }).message;
        if (typeof m === "string" && m.trim()) return m;
      }
    }
  } catch {
    /* ignore */
  }
  return null;
}

function ingestionRunStatusLabel(status: string): string {
  switch (status) {
    case "running":
      return "Running";
    case "succeeded":
      return "Succeeded";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Superseded";
    default:
      return status;
  }
}

function ingestionRunStatusClass(status: string): string {
  switch (status) {
    case "running":
      return "text-emerald-200";
    case "succeeded":
      return "text-emerald-200/90";
    case "failed":
      return "text-red-300";
    case "cancelled":
      return "text-amber-200/90";
    default:
      return "text-secondary";
  }
}

export function DocumentDetailPanel({
  workspaceId,
  documentId,
  listRefreshNonce = 0,
  onClose,
  onDeleted,
  onJobStarted,
}: {
  workspaceId: string;
  documentId: string;
  /** Bumped when the parent document list refetches so status / runs stay aligned with the list. */
  listRefreshNonce?: number;
  onClose: () => void;
  onDeleted: () => void;
  onJobStarted: (docId: string, jobId: string) => void;
}) {
  const [doc, setDoc] = useState<DocDetail | null>(null);
  const [runs, setRuns] = useState<IngestionRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [retryBusy, setRetryBusy] = useState<string | null>(null);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [preview, setPreview] = useState<DeletePreview | null>(null);
  const [cascade, setCascade] = useState<"document_only" | "exclusive_derivatives">(
    "exclusive_derivatives",
  );
  const [previewLoading, setPreviewLoading] = useState(false);
  const [force, setForce] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const toast = useToast();

  const reingestRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/documents/${documentId}`, {
        cache: "no-store",
      });
      const body = (await res.json()) as {
        document?: DocDetail;
        ingestion_runs?: IngestionRun[];
        error?: { message?: string };
      };
      if (!res.ok || !body.document) {
        setError(body.error?.message ?? "Failed to load document");
        return;
      }
      setDoc(body.document);
      setRuns(body.ingestion_runs ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load document");
    } finally {
      setLoading(false);
    }
  }, [workspaceId, documentId]);

  useEffect(() => {
    void load();
  }, [load, listRefreshNonce]);

  const loadPreview = useCallback(async () => {
    setPreviewLoading(true);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/documents/${documentId}/delete-preview?cascade=exclusive_derivatives`,
        { cache: "no-store" },
      );
      const raw = await res.text();
      if (!res.ok) {
        setPreview(null);
        setActionError(messageFromApiJson(raw) ?? "Preview failed");
        return;
      }
      let j: DeletePreview;
      try {
        j = JSON.parse(raw) as DeletePreview;
      } catch {
        setPreview(null);
        setActionError("Invalid preview response");
        return;
      }
      setPreview({
        exclusive_note_count: j.exclusive_note_count,
        shared_note_count: j.shared_note_count,
        entity_touch_count: j.entity_touch_count,
        relationship_touch_count: j.relationship_touch_count,
      });
    } finally {
      setPreviewLoading(false);
    }
  }, [workspaceId, documentId]);

  useEffect(() => {
    if (deleteOpen) void loadPreview();
  }, [deleteOpen, loadPreview]);

  const postRetry = async (from_stage: "parsing" | "generating_notes" | "extracting_graph") => {
    setActionError(null);
    setRetryBusy(from_stage);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/documents/${documentId}/ingestion-runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ from_stage }),
      });
      const raw = await res.text();
      let j: { job_id?: string; error?: { message?: string } } = {};
      try {
        j = JSON.parse(raw) as typeof j;
      } catch {
        /* ignore */
      }
      if (!res.ok) {
        setActionError(messageFromApiJson(raw) ?? `Retry failed (${res.status})`);
        return;
      }
      if (j.job_id) {
        onJobStarted(documentId, j.job_id);
      }
      await load();
    } finally {
      setRetryBusy(null);
    }
  };

  const ingestionActive = doc
    ? new Set([
        "queued",
        "parsing",
        "generating_notes",
        "extracting_graph",
        "building_graph",
      ]).has(doc.status)
    : false;

  const confirmDelete = async () => {
    setActionError(null);
    setDeleteBusy(true);
    try {
      const qs = new URLSearchParams({ cascade });
      if (force) qs.set("force", "true");
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/documents/${documentId}?${qs.toString()}`,
        { method: "DELETE" },
      );
      if (res.status === 204) {
        emitGraphInvalidated();
        toast({
          variant: "success",
          message: "Document deleted",
          description: force ? "Running ingestion cancelled and orphan graph rows cleaned." : undefined,
        });
        onDeleted();
        return;
      }
      const raw = await res.text();
      const msg = messageFromApiJson(raw) ?? `Delete failed (${res.status})`;
      setActionError(msg);
      toast({ variant: "error", message: "Delete failed", description: msg });
    } finally {
      setDeleteBusy(false);
    }
  };

  const onReingestPick = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setActionError(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("replaces_document_id", documentId);
    const res = await fetch(`/api/v1/workspaces/${workspaceId}/documents`, {
      method: "POST",
      body: fd,
    });
    const raw = await res.text();
    try {
      const j = JSON.parse(raw) as {
        documents?: Array<{ id: string; job_id?: string }>;
        job_ids?: string[];
        error?: { message?: string };
      };
      if (!res.ok) {
        setActionError(messageFromApiJson(raw) ?? "Re-ingest failed");
        return;
      }
      const d0 = j.documents?.[0];
      const jid = d0?.job_id ?? j.job_ids?.[0];
      if (d0?.id && jid) {
        onJobStarted(d0.id, jid);
      }
      onClose();
    } catch {
      setActionError("Unexpected re-ingest response");
    }
  };

  return (
    <aside
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-border-strong bg-canvas shadow-xl"
      aria-label="Document details"
    >
      <div className="flex items-start justify-between gap-2 border-b border-border-subtle p-4">
        <div className="min-w-0">
          <p className="truncate text-title-3 text-secondary">
            {loading ? "Loading…" : doc?.original_filename ?? "Document"}
          </p>
          {doc ? (
            <>
              <p className="mt-1 text-caption text-muted">
                {doc.page_count != null ? `${doc.page_count} pages · ` : ""}
                {(doc.byte_size / 1024).toFixed(1)} KB ·{" "}
                <span className="text-secondary">{doc.status.replace(/_/g, " ")}</span>
              </p>
              <p className="mt-1 text-caption text-muted/90">
                Current pipeline stage for this document. Each ingestion run below is one attempt (newest first).
              </p>
            </>
          ) : null}
        </div>
        <button
          type="button"
          className="shrink-0 rounded-md border border-border-strong px-2 py-1 text-caption text-muted hover:bg-surface"
          onClick={onClose}
        >
          Close
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {error ? (
          <p className="text-caption text-red-300" role="alert">
            {error}
          </p>
        ) : null}
        {actionError ? (
          <p className="mb-3 text-caption text-red-300" role="alert">
            {actionError}
          </p>
        ) : null}

        <section aria-label="Retry ingestion" className="mb-6">
          <p className="text-body font-medium text-secondary">Retry from stage</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {(
              [
                ["parsing", "Parsing"],
                ["generating_notes", "Notes"],
                ["extracting_graph", "Graph"],
              ] as const
            ).map(([stage, label]) => (
              <button
                key={stage}
                type="button"
                disabled={retryBusy !== null}
                className="rounded-md border border-border-strong px-2 py-1 text-caption text-secondary hover:bg-surface disabled:opacity-50"
                onClick={() => void postRetry(stage)}
              >
                {retryBusy === stage ? "…" : label}
              </button>
            ))}
          </div>
        </section>

        {doc ? (
          doc.mime_type === "application/pdf" ? (
            <section aria-label="Re-ingest" className="mb-6">
              <p className="text-body font-medium text-secondary">Re-ingest (new PDF)</p>
              <p className="mt-1 text-caption text-muted">
                Upload replaces this document id in metadata; prior episodes and notes are kept until you delete them.
              </p>
              <input
                ref={reingestRef}
                type="file"
                accept="application/pdf,.pdf"
                className="sr-only"
                onChange={(e) => void onReingestPick(e)}
              />
              <button
                type="button"
                className="mt-2 rounded-md bg-accent-primary px-3 py-1.5 text-caption font-medium text-canvas"
                onClick={() => reingestRef.current?.click()}
              >
                Choose replacement PDF
              </button>
            </section>
          ) : (
            <section aria-label="Re-ingest" className="mb-6">
              <p className="text-body font-medium text-secondary">Re-ingest</p>
              <p className="mt-1 text-caption text-muted">
                North conversation transcripts are JSON artifacts. Use{" "}
                <span className="text-secondary">Delete</span> and import again from Agents if you need a fresh copy.
              </p>
            </section>
          )
        ) : null}

        <section aria-label="Ingestion runs" className="mb-6">
          <p className="text-body font-medium text-secondary">Ingestion runs</p>
          <p className="mt-1 text-caption text-muted">
            Retries start a new run. A previous in-flight run is closed as{" "}
            <span className="text-amber-200/90">Superseded</span>, not a pipeline failure.{" "}
            <span className="text-red-300/90">Failed</span> means the attempt ended in error.
          </p>
          {runs.length === 0 ? (
            <p className="mt-2 text-caption text-muted">No runs recorded.</p>
          ) : (
            <ol className="mt-2 space-y-2 border-l border-border-subtle pl-3">
              {runs.map((r) => {
                const isCurrent = r.status === "running" && r.ended_at == null;
                const label = ingestionRunStatusLabel(r.status);
                return (
                  <li key={r.id} className="text-caption text-muted">
                    <span className={`font-medium ${ingestionRunStatusClass(r.status)}`}>{label}</span>
                    {isCurrent ? (
                      <span className="ml-2 rounded bg-emerald-500/15 px-1.5 py-0.5 text-caption text-emerald-200 ring-1 ring-emerald-500/35">
                        Current attempt
                      </span>
                    ) : null}
                    <span className="text-muted"> · </span>
                    {new Date(r.started_at).toLocaleString()}
                    {r.ended_at ? ` → ${new Date(r.ended_at).toLocaleString()}` : ""}
                  </li>
                );
              })}
            </ol>
          )}
        </section>

        <section aria-label="Danger zone">
          <button
            type="button"
            className="rounded-md bg-red-500/80 px-3 py-1.5 text-caption font-medium text-white"
            onClick={() => setDeleteOpen(true)}
          >
            Delete document…
          </button>
        </section>
      </div>

      {deleteOpen ? (
        <div
          className="border-t border-border-strong bg-surface/90 p-4 backdrop-blur"
          role="dialog"
          aria-modal="true"
          aria-label="Confirm delete"
        >
          <p className="text-body font-medium text-secondary">Delete document</p>
          {previewLoading ? (
            <p className="mt-2 text-caption text-muted">Loading preview…</p>
          ) : preview ? (
            <ul className="mt-2 list-inside list-disc text-caption text-muted">
              <li>Exclusive notes: {preview.exclusive_note_count}</li>
              <li>Shared notes (kept): {preview.shared_note_count}</li>
              <li>Entities touched by episodes: {preview.entity_touch_count}</li>
              <li>Relationships touched: {preview.relationship_touch_count}</li>
            </ul>
          ) : (
            <p className="mt-2 text-caption text-muted">No preview available.</p>
          )}
          <fieldset className="mt-3 space-y-2 text-caption text-secondary">
            <legend className="sr-only">Cascade mode</legend>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="cascade"
                checked={cascade === "document_only"}
                onChange={() => setCascade("document_only")}
              />
              Document only (DB cascades remove episodes; notes may become unattached)
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="cascade"
                checked={cascade === "exclusive_derivatives"}
                onChange={() => setCascade("exclusive_derivatives")}
              />
              Remove exclusive derivatives (notes only on this doc + orphan graph rows)
            </label>
          </fieldset>
          {ingestionActive ? (
            <label className="mt-3 flex items-start gap-2 rounded-md border border-amber-400/30 bg-amber-500/10 p-2 text-caption text-amber-100">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
              />
              <span>
                <span className="font-medium">Cancel running ingestion and delete anyway.</span>{" "}
                The current pipeline run will be marked cancelled. Background work already in flight
                will finish against a deleted row (no further effect).
              </span>
            </label>
          ) : null}
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              className="rounded-md border border-border-strong px-3 py-1.5 text-caption text-secondary"
              onClick={() => setDeleteOpen(false)}
              disabled={deleteBusy}
            >
              Cancel
            </button>
            <button
              type="button"
              className="rounded-md bg-red-600 px-3 py-1.5 text-caption font-medium text-white disabled:opacity-60"
              onClick={() => void confirmDelete()}
              disabled={deleteBusy || (ingestionActive && !force)}
              title={
                ingestionActive && !force
                  ? "Document is mid-ingestion. Check the box above to force delete."
                  : undefined
              }
            >
              {deleteBusy ? "Deleting…" : "Confirm delete"}
            </button>
          </div>
        </div>
      ) : null}
    </aside>
  );
}
