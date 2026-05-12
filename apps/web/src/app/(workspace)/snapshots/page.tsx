import { SnapshotsPageClient } from "@/components/snapshots-page-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function SnapshotsPage() {
  const workspace = await getCurrentWorkspace();
  return <SnapshotsPageClient workspaceId={workspace.id} />;
}
