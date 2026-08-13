"use client";

import { useEffect, useRef, useState } from "react";

import {
  DEFAULT_ONTOLOGY,
  OntologyPicker,
  type OntologyChoice,
} from "@/components/ontology-picker";
import { useJobEvents } from "@/lib/job-events";
import { cn } from "@/lib/utils";

const UPLOAD_LIMIT = 52428800;
const UPLOAD_ACCEPT =
  "application/pdf,.pdf,text/plain,.txt,text/markdown,.md,.markdown,message/rfc822,.eml";

type CollectionRow = { id: string; name: string };

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

export function DocumentsUploadChip({
  workspaceId,
  className,
}: {
  workspaceId: string;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ontology, setOntology] = useState<OntologyChoice>(DEFAULT_ONTOLOGY);
  const [collections, setCollections] = useState<CollectionRow[]>([]);
  const [collection, setCollection] = useState("");
  const { registerActiveJob, requestOpenLogConsole } = useJobEvents();

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(`/api/v1/workspaces/${workspaceId}/document-collections`, {
          cache: "no-store",
        });
        const body = (await res.json().catch(() => ({}))) as { items?: CollectionRow[] };
        if (!cancelled && res.ok) setCollections(body.items ?? []);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const uploadFiles = async (files: File[]) => {
    setError(null);
    setBusy(true);
    try {
      const fd = new FormData();
      for (const f of files) {
        if (f.size > UPLOAD_LIMIT) {
          setError(`"${f.name}" exceeds maximum upload size`);
          return;
        }
        if (!isAcceptedUpload(f)) {
          setError(`"${f.name}" is not an accepted type (PDF, TXT, MD, EML)`);
          return;
        }
        fd.append("file", f);
      }
      fd.append("ontology_name", ontology.name);
      fd.append("ontology_version", ontology.version);
      const coll = collection.trim();
      if (coll) {
        const existing = collections.find(
          (c) => c.name.toLowerCase() === coll.toLowerCase() || c.id === coll,
        );
        if (existing) fd.append("collection_id", existing.id);
        else fd.append("collection_name", coll);
      }

      const res = await fetch(`/api/v1/workspaces/${workspaceId}/documents`, {
        method: "POST",
        body: fd,
      });
      const raw = await res.text();
      if (!res.ok) {
        try {
          const j = JSON.parse(raw) as { error?: { message?: string } };
          setError(j.error?.message ?? `Upload failed (${res.status})`);
        } catch {
          setError(`Upload failed (${res.status})`);
        }
        return;
      }

      const body = JSON.parse(raw) as {
        documents: Array<{ id: string; job_id?: string }>;
        job_ids: string[];
      };
      body.documents.forEach((d, i) => {
        const jid = d.job_id ?? body.job_ids[i];
        if (jid) {
          registerActiveJob(jid, workspaceId, d.id, "document_parse");
          requestOpenLogConsole();
        }
      });
    } catch {
      setError("Upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <span className={cn("inline-flex flex-wrap items-center gap-2", className)}>
      <input
        list={`upload-chip-collections-${workspaceId}`}
        value={collection}
        onChange={(e) => setCollection(e.target.value)}
        placeholder="Collection"
        className="w-28 rounded border border-input bg-card px-2 py-1 text-caption text-muted-foreground"
      />
      <datalist id={`upload-chip-collections-${workspaceId}`}>
        {collections.map((c) => (
          <option key={c.id} value={c.name} />
        ))}
      </datalist>
      <OntologyPicker
        workspaceId={workspaceId}
        value={ontology}
        onChange={setOntology}
        className="min-w-[10rem]"
        compact
      />
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
      <button
        type="button"
        disabled={busy}
        className="rounded-md border border-input bg-card px-2 py-1 text-caption text-muted-foreground hover:bg-secondary disabled:opacity-50"
        onClick={() => inputRef.current?.click()}
      >
        {busy ? "Uploading…" : "Upload"}
      </button>
      {error ? <span className="text-[10px] text-destructive">{error}</span> : null}
    </span>
  );
}
