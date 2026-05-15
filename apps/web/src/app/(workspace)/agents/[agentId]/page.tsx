import { getCurrentWorkspace } from "@/lib/auth";

import { AgentDetailPanel } from "@/components/agent-detail-panel";

export const dynamic = "force-dynamic";

export default async function AgentDetailPage({ params }: { params: { agentId: string } }) {
  const workspace = await getCurrentWorkspace();
  return (
    <div className="flex min-h-[520px] flex-col gap-4 p-2">
      <AgentDetailPanel workspaceId={workspace.id} agentId={params.agentId} />
    </div>
  );
}
