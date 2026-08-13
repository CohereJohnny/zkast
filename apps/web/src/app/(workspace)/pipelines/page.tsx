import { PipelinesPageClient } from "@/components/pipelines-page-client";
import { getCurrentWorkspace } from "@/lib/auth";
import { Suspense } from "react";

export const dynamic = "force-dynamic";

export default async function PipelinesPage() {
  const workspace = await getCurrentWorkspace();
  return (
    <div className="flex min-h-[520px] flex-col gap-4 p-2">
      <Suspense fallback={<p className="text-p text-muted-foreground">Loading pipelines…</p>}>
        <PipelinesPageClient workspaceId={workspace.id} />
      </Suspense>
    </div>
  );
}
