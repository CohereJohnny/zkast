import { EmptyState } from "@/components/empty-state";

export default function NotesPage() {
  return (
    <EmptyState
      title="No notes in this workspace"
      description="Atomic notes appear here after documents are ingested — or create one manually later."
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
