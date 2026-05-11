import { EmptyState } from "@/components/empty-state";

export default function DocumentsPage() {
  return (
    <EmptyState
      title="No documents yet"
      description="Upload PDFs to triage ingestion runs and feed your working graph."
      cta={
        <button
          type="button"
          disabled
          className="cursor-not-allowed rounded-md bg-accent-primary px-4 py-2 text-body font-medium text-canvas opacity-45"
        >
          Upload a document
        </button>
      }
    />
  );
}
