import { JobsPageClient } from "@/components/jobs-page-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function JobsPage() {
  const workspace = await getCurrentWorkspace();
  return <JobsPageClient workspaceId={workspace.id} />;
}
