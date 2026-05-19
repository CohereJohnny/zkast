import { DocumentsPanel } from "@/components/documents-panel";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function ConversationsPage() {
  const workspace = await getCurrentWorkspace();
  return (
    <div className="flex min-h-[520px] flex-col gap-4 p-2">
      <DocumentsPanel workspaceId={workspace.id} variant="full" library="conversations" />
    </div>
  );
}
