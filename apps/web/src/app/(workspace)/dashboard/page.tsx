import { Suspense } from "react";

export const dynamic = "force-dynamic";

import { DashboardPageClient } from "@/components/dashboard-page-client";
import { getCurrentWorkspace } from "@/lib/auth";

export default async function DashboardPage() {
  const workspace = await getCurrentWorkspace();
  return (
    <div className="flex min-h-[520px] flex-col gap-4 p-2">
      <Suspense
        fallback={
          <p className="p-4 text-caption text-muted-foreground">Loading dashboard…</p>
        }
      >
        <DashboardPageClient workspaceId={workspace.id} />
      </Suspense>
    </div>
  );
}
