import type { ReactNode } from "react";

export type ConversationMemoryStats = {
  notes?: number;
  amem_embeddings?: number;
  document_status?: string;
  ingest_digest?: string | null;
  /** Agent list: North cache only, not yet imported. */
  cached?: boolean;
  /** Agent list: ingest content changed since last import. */
  outdated?: boolean;
};

function TelemetryLine({ parts }: { parts: ReactNode[] }) {
  if (parts.length === 0) return null;
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-caption text-muted">
      {parts.map((part, i) => (
        <span key={i} className="inline-flex items-center gap-2">
          {i > 0 ? <span aria-hidden>·</span> : null}
          {part}
        </span>
      ))}
    </p>
  );
}

export function ConversationMemoryTelemetry({
  memory,
  documentStatus,
  notImported,
  importing,
}: {
  memory?: ConversationMemoryStats | null;
  /** Fallback pipeline status when memory.document_status is absent. */
  documentStatus?: string;
  notImported?: boolean;
  importing?: boolean;
}) {
  if (importing) {
    return <p className="text-caption text-muted">Import in progress…</p>;
  }
  if (notImported) {
    return <p className="text-caption text-muted">Cached from North · not imported</p>;
  }

  const mem = memory ?? {};
  const parts: ReactNode[] = [];
  if (typeof mem.notes === "number") {
    parts.push(
      <span key="notes">
        <strong className="text-secondary">{mem.notes}</strong> notes
      </span>,
    );
  }
  if (typeof mem.amem_embeddings === "number") {
    parts.push(
      <span key="amem">
        <strong className="text-secondary">{mem.amem_embeddings}</strong> A-MEM indexed
      </span>,
    );
  }
  const status = mem.document_status ?? documentStatus;
  if (status) {
    parts.push(<span key="status">{status.replace(/_/g, " ")}</span>);
  }
  if (mem.ingest_digest) {
    parts.push(
      <span key="digest" className="font-mono">
        digest {mem.ingest_digest}…
      </span>,
    );
  }
  if (mem.outdated) {
    parts.push(
      <span key="outdated" className="text-secondary">
        update available
      </span>,
    );
  }
  return <TelemetryLine parts={parts} />;
}
