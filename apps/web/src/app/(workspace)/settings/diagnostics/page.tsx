import { DiagnosticsPageClient } from "@/components/diagnostics-page-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function DiagnosticsPage() {
  const workspace = await getCurrentWorkspace();
  return <DiagnosticsPageClient workspaceId={workspace.id} />;
}
