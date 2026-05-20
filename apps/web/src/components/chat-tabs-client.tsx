"use client";

import { useState } from "react";

import { ChatComparePanel } from "@/components/chat-compare-panel";
import { ChatPanel } from "@/components/chat-panel";

/**
 * Sprint 6b — tabbed shell over the chat surface.
 *
 * Two views share the route:
 *
 * - ``Chat`` — the regular grounded-chat panel with the per-session
 *   retrieval strategy selector.
 * - ``Compare`` — side-by-side execution of Naive RAG, GraphRAG, and
 *   Hybrid against the same question.
 *
 * Keeping these on the same page (rather than a separate admin route)
 * is the Sprint 6b intent: every user should be able to inspect how
 * the retrieval strategies differ, not just admins.
 */

type Tab = "chat" | "compare";

export function ChatTabsClient({
  workspaceId,
  initialAgentId,
}: {
  workspaceId: string;
  /** Pre-fills North agent scope when arriving from an agent-scoped surface. */
  initialAgentId?: string | null;
}) {
  const [tab, setTab] = useState<Tab>("chat");

  return (
    <div className="flex h-full flex-col gap-3">
      <nav
        aria-label="Chat views"
        className="flex items-center gap-1 rounded-md border border-border-subtle bg-surface/40 p-0.5"
      >
        <TabButton active={tab === "chat"} onClick={() => setTab("chat")}>
          Chat
        </TabButton>
        <TabButton
          active={tab === "compare"}
          onClick={() => setTab("compare")}
        >
          Compare strategies
        </TabButton>
      </nav>
      <div className="min-h-0 flex-1 overflow-auto">
        {tab === "chat" ? (
          <ChatPanel workspaceId={workspaceId} initialAgentId={initialAgentId} />
        ) : (
          <ChatComparePanel workspaceId={workspaceId} />
        )}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={
        active
          ? "cursor-pointer rounded px-3 py-1 text-caption font-medium text-canvas bg-accent-primary transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
          : "cursor-pointer rounded px-3 py-1 text-caption text-secondary transition-colors duration-150 hover:bg-surface-raised focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
      }
    >
      {children}
    </button>
  );
}
