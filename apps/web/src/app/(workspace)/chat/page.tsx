import { EmptyState } from "@/components/empty-state";

export default function ChatPage() {
  return (
    <EmptyState
      title="No chat sessions"
      description="Grounded answers will cite your notes and graph — start once documents exist."
      cta={
        <button
          type="button"
          disabled
          className="cursor-not-allowed rounded-md bg-accent-primary px-4 py-2 text-body font-medium text-canvas opacity-45"
        >
          Start a conversation
        </button>
      }
    />
  );
}
