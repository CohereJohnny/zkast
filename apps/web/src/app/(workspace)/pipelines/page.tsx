import { PipelinesPageClient } from "@/components/pipelines-page-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function PipelinesPage() {
  const workspace = await getCurrentWorkspace();
  return (
    <div className="flex min-h-[520px] flex-col gap-4 p-2">
      <PipelinesPageClient workspaceId={workspace.id} />
    </div>
  );
}
