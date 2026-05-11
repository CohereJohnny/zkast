import type { ReactNode } from "react";

import { WorkspaceShell } from "@/components/workspace-shell";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function WorkspaceLayout({
  children,
}: {
  children: ReactNode;
}) {
  const workspace = await getCurrentWorkspace();
  return <WorkspaceShell workspaceName={workspace.name}>{children}</WorkspaceShell>;
}
