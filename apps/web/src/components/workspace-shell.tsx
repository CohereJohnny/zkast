import type { ReactNode } from "react";

import { ChatDrawerSlot } from "@/components/chat-drawer-slot";
import { LeftRail } from "@/components/left-rail";

export async function WorkspaceShell({
  workspaceName,
  children,
}: {
  workspaceName: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-canvas">
      <LeftRail workspaceName={workspaceName} />
      <div className="pl-[calc(13rem+2rem)] pr-14 pt-4 pb-4">
        <div className="flex min-h-[calc(100vh-2rem)] flex-col gap-4">
          <div className="grid min-h-[480px] flex-1 grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)_minmax(0,1fr)]">
            <section
              aria-label="Documents panel placeholder"
              className="rounded-lg border border-border-subtle bg-surface/80 p-4 text-caption text-muted"
            >
              <p className="text-title-3 text-secondary">Documents panel</p>
              <p className="mt-2">
                Resize handles and live content ship in later sprints.
              </p>
            </section>
            <section
              id="main-content"
              tabIndex={-1}
              aria-label="Main workspace panel"
              className="flex min-h-[320px] flex-col rounded-lg border border-border-strong bg-surface outline-none"
            >
              {children}
            </section>
            <section
              aria-label="Graph panel placeholder"
              className="rounded-lg border border-border-subtle bg-surface/80 p-4 text-caption text-muted"
            >
              <p className="text-title-3 text-secondary">Graph panel</p>
              <p className="mt-2">
                Working graph canvas will anchor here by default.
              </p>
            </section>
          </div>
        </div>
      </div>
      <ChatDrawerSlot />
    </div>
  );
}
