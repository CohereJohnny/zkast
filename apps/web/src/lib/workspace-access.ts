import { getCurrentWorkspace } from "@/lib/auth";

export async function requireMatchingWorkspace(workspaceId: string): Promise<Response | null> {
  const ws = await getCurrentWorkspace();
  if (ws.id !== workspaceId) {
    return Response.json(
      {
        error: {
          code: "forbidden",
          message: "Workspace does not match the current session workspace",
        },
      },
      { status: 403 },
    );
  }
  return null;
}
