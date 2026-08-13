import { GraphWorkspacePanel } from "@/components/graph-workspace-panel";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function GraphPage() {
  const workspace = await getCurrentWorkspace();
  return (
    <div className="flex h-full min-h-0 flex-1 flex-col p-2">
      <GraphWorkspacePanel workspaceId={workspace.id} fullHeight />
    </div>
  );
}
