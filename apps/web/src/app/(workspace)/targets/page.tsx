import { EmptyState } from "@/components/empty-state";

export default function TargetsPage() {
  return (
    <EmptyState
      title="No external targets configured"
      description="Connect Neo4j or Postgres + AGE when you are ready to persist reviewed snapshots."
      cta={
        <button
          type="button"
          disabled
          className="cursor-not-allowed rounded-md bg-primary px-4 py-2 text-p font-medium text-primary-foreground opacity-45"
        >
          Add target
        </button>
      }
    />
  );
}
