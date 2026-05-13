import { ChatTabsClient } from "@/components/chat-tabs-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function ChatPage() {
  const workspace = await getCurrentWorkspace();
  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col px-4 py-4">
      <ChatTabsClient workspaceId={workspace.id} />
    </div>
  );
}
