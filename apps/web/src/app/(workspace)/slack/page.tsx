import { SlackPageClient } from "@/components/slack-page-client";
import { getCurrentWorkspace } from "@/lib/auth";
import { pipelineFetch } from "@/lib/pipeline-client";

export const dynamic = "force-dynamic";

type SlackSource = {
  source_id: string;
  channel_id: string;
  name: string;
  sync?: Record<string, unknown> | null;
};

async function loadInitialSlackSources(workspaceId: string): Promise<SlackSource[]> {
  try {
    const res = await pipelineFetch(
      `/internal/v1/workspaces/${encodeURIComponent(workspaceId)}/slack/sources`,
      { method: "GET", throwOnError: false },
    );
    if (!res.ok) return [];
    const body = (await res.json()) as { items?: SlackSource[] };
    return body.items ?? [];
  } catch {
    return [];
  }
}

export default async function SlackPage() {
  const workspace = await getCurrentWorkspace();
  const initialSources = await loadInitialSlackSources(workspace.id);
  return (
    <div className="flex min-h-[520px] flex-col gap-4 p-2">
      <SlackPageClient workspaceId={workspace.id} initialSources={initialSources} />
    </div>
  );
}
