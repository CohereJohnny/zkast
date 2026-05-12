import { NotesPageClient } from "@/components/notes-page-client";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function NotesPage() {
  const workspace = await getCurrentWorkspace();
  return <NotesPageClient workspaceId={workspace.id} />;
}
