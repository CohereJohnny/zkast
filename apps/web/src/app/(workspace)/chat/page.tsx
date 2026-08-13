import { ChatTabsClient } from "@/components/chat-tabs-client";
import { getCurrentWorkspace } from "@/lib/auth";
import { Suspense } from "react";

export const dynamic = "force-dynamic";

function ChatTabsWithParams({
  workspaceId,
  initialAgentId,
}: {
  workspaceId: string;
  initialAgentId?: string | null;
}) {
  return (
    <ChatTabsClient workspaceId={workspaceId} initialAgentId={initialAgentId} />
  );
}

export default async function ChatPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const workspace = await getCurrentWorkspace();
  const params = (await searchParams) ?? {};
  const raw = params.agent_id ?? params.agentId;
  const initialAgentId = Array.isArray(raw) ? raw[0] : raw;
  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col px-4 py-4">
      <Suspense fallback={<p className="text-p text-muted-foreground">Loading chat…</p>}>
        <ChatTabsWithParams
          workspaceId={workspace.id}
          initialAgentId={initialAgentId ?? null}
        />
      </Suspense>
    </div>
  );
}
