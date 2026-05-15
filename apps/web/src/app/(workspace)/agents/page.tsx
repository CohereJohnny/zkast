import { AgentsPanel } from "@/components/agents-panel";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function AgentsPage() {
  const workspace = await getCurrentWorkspace();
  return (
    <div className="flex min-h-[520px] flex-col gap-4 p-2">
      <AgentsPanel workspaceId={workspace.id} />
    </div>
  );
}
