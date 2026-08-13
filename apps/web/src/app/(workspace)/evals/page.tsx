import { EvalsPanel } from "@/components/evals-panel";
import { getCurrentWorkspace } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function EvalsPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const workspace = await getCurrentWorkspace();
  const params = (await searchParams) ?? {};
  const rawRun = params.run_id ?? params.runId;
  const initialRunId = Array.isArray(rawRun) ? rawRun[0] : rawRun;
  const rawAgent = params.agent_id ?? params.agentId;
  const initialAgentId = Array.isArray(rawAgent) ? rawAgent[0] : rawAgent;
  const rawModes = params.modes;
  const modesStr = Array.isArray(rawModes) ? rawModes[0] : rawModes;
  const initialModes = modesStr
    ? modesStr.split(",").map((m) => m.trim()).filter(Boolean)
    : params.preset === "fair"
      ? ["graph", "ms_graphrag"]
      : null;
  const initialNotes =
    params.preset === "fair" ? "Harness preset 1 — fair Graphiti vs MS GraphRAG" : null;

  return (
    <div className="flex min-h-[calc(100vh-8rem)] flex-col gap-4 px-4 py-4">
      <EvalsPanel
        workspaceId={workspace.id}
        initialRunId={initialRunId ?? null}
        initialModes={initialModes}
        initialAgentId={initialAgentId ?? null}
        initialNotes={initialNotes}
      />
    </div>
  );
}
