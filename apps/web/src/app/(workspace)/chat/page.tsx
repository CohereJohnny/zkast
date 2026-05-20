import { ChatTabsClient } from "@/components/chat-tabs-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

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
      <ChatTabsClient
        workspaceId={workspace.id}
        initialAgentId={initialAgentId ?? null}
      />
    </div>
  );
}
