import { EmptyState } from "@/components/empty-state";

export default function SnapshotsPage() {
  return (
    <EmptyState
      title="No snapshots yet"
      description="Snapshots freeze the working graph for review before you persist to an external target."
      cta={
        <button
          type="button"
          disabled
          className="cursor-not-allowed rounded-md bg-accent-primary px-4 py-2 text-body font-medium text-canvas opacity-45"
        >
          Create snapshot
        </button>
      }
    />
  );
}
