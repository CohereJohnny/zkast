import { EmptyState } from "@/components/empty-state";

export default function GraphPage() {
  return (
    <EmptyState
      title="Graph is empty"
      description="Upload your first document to extract entities and relationships into the working graph."
      cta={
        <button
          type="button"
          disabled
          className="cursor-not-allowed rounded-md bg-accent-primary px-4 py-2 text-body font-medium text-canvas opacity-45"
        >
          Upload your first document
        </button>
      }
    />
  );
}
