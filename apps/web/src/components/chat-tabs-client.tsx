"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import {
  ChatComparePanel,
  HARNESS_COMPARE_MODES,
} from "@/components/chat-compare-panel";
import { ChatPanel } from "@/components/chat-panel";
import type { RetrievalMode } from "@/components/chat-panel";

type Tab = "chat" | "compare";

function parseHarnessModes(raw: string | null): RetrievalMode[] | null {
  if (!raw) return null;
  const modes = raw
    .split(",")
    .map((m) => m.trim())
    .filter(Boolean) as RetrievalMode[];
  return modes.length > 0 ? modes : null;
}

export function ChatTabsClient({
  workspaceId,
  initialAgentId,
}: {
  workspaceId: string;
  initialAgentId?: string | null;
}) {
  const searchParams = useSearchParams();
  const harnessCompare = searchParams.get("compare") === "harness";
  const harnessModes = useMemo(
    () => parseHarnessModes(searchParams.get("modes")) ?? HARNESS_COMPARE_MODES,
    [searchParams],
  );
  const [tab, setTab] = useState<Tab>(harnessCompare ? "compare" : "chat");

  return (
    <div className="flex h-full flex-col gap-3">
      <nav
        aria-label="Chat views"
        className="flex items-center gap-1 rounded-md border border-border bg-card/40 p-0.5"
      >
        <TabButton active={tab === "chat"} onClick={() => setTab("chat")}>
          Chat
        </TabButton>
        <TabButton
          active={tab === "compare"}
          onClick={() => setTab("compare")}
        >
          {harnessCompare ? "Graph harness compare" : "Compare strategies"}
        </TabButton>
      </nav>
      <div className="min-h-0 flex-1 overflow-auto">
        {tab === "chat" ? (
          <ChatPanel workspaceId={workspaceId} initialAgentId={initialAgentId} />
        ) : harnessCompare ? (
          <ChatComparePanel
            workspaceId={workspaceId}
            modes={harnessModes}
            initialAgentId={initialAgentId}
            title="Graphiti vs MS GraphRAG"
            description="Submit one question scoped to this memory space. Graphiti uses live graph retrieval; MS GraphRAG uses global search over community reports from the latest built index."
          />
        ) : (
          <ChatComparePanel workspaceId={workspaceId} initialAgentId={initialAgentId} />
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
          ? "cursor-pointer rounded px-3 py-1 text-caption font-medium text-primary-foreground bg-primary transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          : "cursor-pointer rounded px-3 py-1 text-caption text-muted-foreground transition-colors duration-150 hover:bg-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      }
    >
      {children}
    </button>
  );
}
