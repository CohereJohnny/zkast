"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";

export function CompareRunModal({
  open,
  onClose,
  workspaceId: _workspaceId,
  agentId,
}: {
  open: boolean;
  onClose: () => void;
  workspaceId: string;
  agentId?: string | null;
}) {
  void _workspaceId;
  const router = useRouter();
  if (!open) return null;

  const agentQs = agentId ? `&agent_id=${encodeURIComponent(agentId)}` : "";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="compare-run-title"
    >
      <div className="w-full max-w-md rounded-lg border border-border bg-card p-4 shadow-lg">
        <h2 id="compare-run-title" className="text-h5 text-foreground">
          Run comparison
        </h2>
        <p className="mt-1 text-caption text-muted-foreground">
          Compare Graphiti graph retrieval vs MS GraphRAG community search for this memory space.
        </p>
        <div className="mt-4 flex flex-col gap-2">
          <Button
            onClick={() => {
              onClose();
              const agentPart = agentId
                ? `&agent_id=${encodeURIComponent(agentId)}`
                : "";
              router.push(
                `/chat?compare=harness&modes=graph,ms_graphrag${agentPart}`,
              );
            }}
          >
            Quick compare (chat)
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              onClose();
              router.push(`/evals?modes=graph,ms_graphrag&preset=fair${agentQs}`);
            }}
          >
            Scored eval (batch)
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              onClose();
              router.push("/pipelines?harness=1");
            }}
          >
            Open in Lab
          </Button>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}
