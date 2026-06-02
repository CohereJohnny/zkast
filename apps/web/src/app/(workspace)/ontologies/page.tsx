import { OntologiesPageClient } from "@/components/ontologies-page-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function OntologiesPage() {
  const workspace = await getCurrentWorkspace();
  return (
    <div className="flex min-h-[520px] flex-col gap-4 p-2">
      <OntologiesPageClient workspaceId={workspace.id} />
    </div>
  );
}
