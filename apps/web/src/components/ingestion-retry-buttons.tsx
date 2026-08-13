"use client";

import { useState } from "react";

import {
  postDocumentIngestionRetry,
  type IngestionRetryStage,
} from "@/lib/ingestion-retry";

const STAGES: { stage: IngestionRetryStage; label: string }[] = [
  { stage: "parsing", label: "Parsing" },
  { stage: "generating_notes", label: "Notes" },
  { stage: "extracting_graph", label: "Graph" },
];

export function IngestionRetryButtons({
  workspaceId,
  documentId,
  disabled = false,
  onJobStarted,
  onError,
  onComplete,
  className,
}: {
  workspaceId: string;
  documentId: string;
  disabled?: boolean;
  onJobStarted?: (docId: string, jobId: string) => void;
  onError?: (message: string) => void;
  onComplete?: () => void;
  className?: string;
}) {
  const [retryBusy, setRetryBusy] = useState<IngestionRetryStage | null>(null);

  const postRetry = async (from_stage: IngestionRetryStage) => {
    setRetryBusy(from_stage);
    try {
      const result = await postDocumentIngestionRetry(workspaceId, documentId, from_stage);
      if (!result.ok) {
        onError?.(result.error);
        return;
      }
      if (result.jobId) {
        onJobStarted?.(documentId, result.jobId);
      }
      onComplete?.();
    } finally {
      setRetryBusy(null);
    }
  };

  return (
    <div className={className}>
      <div className="flex flex-wrap gap-2">
        {STAGES.map(({ stage, label }) => (
          <button
            key={stage}
            type="button"
            disabled={disabled || retryBusy !== null}
            className="rounded-md border border-input px-2 py-1 text-caption text-muted-foreground hover:bg-card disabled:opacity-50"
            onClick={() => void postRetry(stage)}
          >
            {retryBusy === stage ? "…" : label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function IngestionRetrySection({
  workspaceId,
  documentId,
  disabled = false,
  description,
  onJobStarted,
  onError,
  onComplete,
  className,
}: {
  workspaceId: string;
  documentId: string;
  disabled?: boolean;
  description?: string;
  onJobStarted?: (docId: string, jobId: string) => void;
  onError?: (message: string) => void;
  onComplete?: () => void;
  className?: string;
}) {
  return (
    <section aria-label="Retry ingestion" className={className}>
      <p className="text-p font-medium text-muted-foreground">Retry from stage</p>
      {description ? (
        <p className="mt-1 text-caption text-muted-foreground">{description}</p>
      ) : null}
      <IngestionRetryButtons
        workspaceId={workspaceId}
        documentId={documentId}
        disabled={disabled}
        onJobStarted={onJobStarted}
        onError={onError}
        onComplete={onComplete}
        className="mt-2"
      />
    </section>
  );
}
