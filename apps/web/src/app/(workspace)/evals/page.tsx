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
  const raw = params.run_id ?? params.runId;
  const initialRunId = Array.isArray(raw) ? raw[0] : raw;
  return (
    <div className="flex min-h-[calc(100vh-8rem)] flex-col gap-4 px-4 py-4">
      <EvalsPanel workspaceId={workspace.id} initialRunId={initialRunId ?? null} />
    </div>
  );
}
