import { EmptyState } from "@/components/empty-state";

export default function NotesPage() {
  return (
    <EmptyState
      title="Notes aren’t wired up yet"
      description="Ingestion stores PDF chunks as episodes in Postgres for the pipeline. Listing and editing them as notes in this UI ships in a later sprint."
      cta={
        <button
          type="button"
          disabled
          className="cursor-not-allowed rounded-md bg-accent-primary px-4 py-2 text-body font-medium text-canvas opacity-45"
        >
          New note
        </button>
      }
    />
  );
}
