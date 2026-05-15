import { Suspense } from "react";

import { NotesPageClient } from "@/components/notes-page-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function NotesPage() {
  const workspace = await getCurrentWorkspace();
  return (
    <Suspense fallback={<p className="p-4 text-caption text-muted">Loading notes…</p>}>
      <NotesPageClient workspaceId={workspace.id} />
    </Suspense>
  );
}
