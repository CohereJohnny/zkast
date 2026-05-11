import type { ReactNode } from "react";

import { ChatDrawerSlot } from "@/components/chat-drawer-slot";
import { LeftRail } from "@/components/left-rail";
import { WorkspaceMainGrid } from "@/components/workspace-main-grid";

export async function WorkspaceShell({
  workspaceName,
  workspaceId,
  children,
}: {
  workspaceName: string;
  workspaceId: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-canvas">
      <LeftRail workspaceName={workspaceName} />
      <div className="pl-[calc(13rem+2rem)] pr-14 pt-4 pb-4">
        <WorkspaceMainGrid workspaceId={workspaceId}>{children}</WorkspaceMainGrid>
      </div>
      <ChatDrawerSlot />
    </div>
  );
}
