import { SettingsPageClient } from "@/components/settings-page-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const workspace = await getCurrentWorkspace();
  return <SettingsPageClient workspaceId={workspace.id} />;
}
