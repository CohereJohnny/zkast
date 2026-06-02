import { SlackPageClient } from "@/components/slack-page-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function SlackPage() {
  const workspace = await getCurrentWorkspace();
  return (
    <div className="flex min-h-[520px] flex-col gap-4 p-2">
      <SlackPageClient workspaceId={workspace.id} />
    </div>
  );
}
