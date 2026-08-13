import { Suspense } from "react";

import { DocumentSourcePageClient } from "@/components/document-source-page-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default function DocumentSourcePage({ params }: { params: { documentId: string } }) {
  const workspacePromise = getCurrentWorkspace();
  return (
    <Suspense
      fallback={
        <div className="p-2 text-caption text-muted-foreground" role="status">
          Loading source…
        </div>
      }
    >
      <DocumentSourcePageAsync workspacePromise={workspacePromise} documentId={params.documentId} />
    </Suspense>
  );
}

async function DocumentSourcePageAsync({
  workspacePromise,
  documentId,
}: {
  workspacePromise: ReturnType<typeof getCurrentWorkspace>;
  documentId: string;
}) {
  const workspace = await workspacePromise;
  return <DocumentSourcePageClient workspaceId={workspace.id} documentId={documentId} />;
}
