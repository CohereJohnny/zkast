import { EmptyState } from "@/components/empty-state";

export default function SettingsPage() {
  return (
    <EmptyState
      title="Workspace settings"
      description="Pipeline models, members, API keys, and audit trails will live here in upcoming sprints."
      cta={
        <button
          type="button"
          disabled
          className="cursor-not-allowed rounded-md border border-border-strong px-4 py-2 text-body font-medium text-secondary opacity-45"
        >
          Save changes
        </button>
      }
    />
  );
}
