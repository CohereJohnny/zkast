export const dynamic = "force-dynamic";

import { DashboardPageClient } from "@/components/dashboard-page-client";
import { getCurrentWorkspace } from "@/lib/auth";

export default async function DashboardPage() {
  const workspace = await getCurrentWorkspace();
  return (
    <div className="flex min-h-[520px] flex-col gap-4 p-2">
      <DashboardPageClient workspaceId={workspace.id} />
    </div>
  );
}
