"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import { useToast } from "@/components/feedback-provider";
import {
  SourceScopeFilter,
  type SourceScopeSelection,
} from "@/components/filters/source-scope-filter";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useJobEvents } from "@/lib/job-events";
import { graphragJobId, startGraphragIndex } from "@/lib/graphrag-build";
import { fetchWithTimeout } from "@/lib/fetch-with-timeout";
import { cn } from "@/lib/utils";

export { graphragJobId };

type AgentRow = {
  id: string;
  display_name?: string | null;
  external_agent_id?: string | null;
  provider?: string | null;
};

export type GraphragIndexRow = {
  id: string;
  agent_id?: string | null;
  collection_id?: string | null;
  status: string;
  stats?: Record<string, unknown> | null;
  failure_reason?: string | null;
  provider?: string | null;
  created_at?: string | null;
};

type Space = {
  key: string;
  agentId: string | null;
  collectionId: string | null;
  label: string;
  kind: "workspace" | "channel" | "agent" | "collection";
};

function statusVariant(status: string): "success" | "caution" | "secondary" | "destructive" | "info" {
  if (status === "ready") return "success";
  if (status === "pending" || status === "running") return "caution";
  if (status === "failed") return "destructive";
  return "secondary";
}

export function GraphragIndexControls({
  workspaceId,
  selectedAgentId,
  selectedCollectionId,
  selectedIndexId,
  onIndexChange,
  onActiveIndexChange,
  onRegisterBuild,
  compact = false,
}: {
  workspaceId: string;
  selectedAgentId?: string | null;
  selectedCollectionId?: string | null;
  selectedIndexId?: string | null;
  onIndexChange?: (
    indexId: string | null,
    agentId: string | null,
    collectionId?: string | null,
  ) => void;
  onActiveIndexChange?: (index: GraphragIndexRow | null) => void;
  /** Parent can trigger rebuild from blocked-state panels. */
  onRegisterBuild?: (build: () => void) => void;
  /** Toolbar layout for embedded Graph page vs full table. */
  compact?: boolean;
}) {
  const toast = useToast();
  const { registerActiveJob, unregisterActiveJob, requestOpenLogConsole } = useJobEvents();
  const base = `/api/v1/workspaces/${encodeURIComponent(workspaceId)}`;

  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [indexes, setIndexes] = useState<GraphragIndexRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [maxDocs, setMaxDocs] = useState(200);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [corpusDelta, setCorpusDelta] = useState<{
    buildDocuments: number;
    corpusNow: number;
    endedAt?: string | null;
    stale?: boolean;
  } | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const failedNotifiedRef = useRef<Set<string>>(new Set());
  const registeredBuildJobsRef = useRef<Set<string>>(new Set());
  const userTriggeredBuildRef = useRef<Set<string>>(new Set());
  const indexStatusRef = useRef<Map<string, string>>(new Map());

  const loadIndexes = useCallback(async () => {
    try {
      const res = await fetchWithTimeout(`${base}/graphrag/indexes`, {
        cache: "no-store",
        timeoutMs: 20_000,
      });
      const body = (await res.json()) as { items?: GraphragIndexRow[] };
      if (res.ok) setIndexes(body.items ?? []);
    } catch {
      /* transient */
    }
  }, [base]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [aRes] = await Promise.all([
        fetch(`${base}/north/agents`, { cache: "no-store" }),
        loadIndexes(),
      ]);
      const aBody = (await aRes.json().catch(() => ({}))) as { items?: AgentRow[] };
      if (aRes.ok) setAgents(aBody.items ?? []);
    } finally {
      setLoading(false);
    }
  }, [base, loadIndexes]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const anyActive = useMemo(
    () => indexes.some((i) => i.status === "pending" || i.status === "running"),
    [indexes],
  );
  useEffect(() => {
    if (anyActive && !pollRef.current) {
      pollRef.current = setInterval(() => void loadIndexes(), 5000);
    } else if (!anyActive && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [anyActive, loadIndexes]);

  const spaces = useMemo<Space[]>(() => {
    const out: Space[] = [
      { key: "ws", agentId: null, collectionId: null, label: "Whole workspace", kind: "workspace" },
    ];
    for (const a of agents) {
      const isSlack = a.provider === "slack";
      const name = (a.display_name ?? "").trim() || a.external_agent_id || a.id;
      out.push({
        key: a.id,
        agentId: a.id,
        collectionId: null,
        label: isSlack ? `#${name}` : name,
        kind: isSlack ? "channel" : "agent",
      });
    }
    return out;
  }, [agents]);

  const latestFor = useCallback(
    (agentId: string | null, collectionId: string | null = null): GraphragIndexRow | null => {
      const matches = indexes.filter(
        (i) =>
          (i.agent_id ?? null) === agentId && (i.collection_id ?? null) === collectionId,
      );
      if (matches.length === 0) return null;
      return matches.reduce((a, b) =>
        (a.created_at ?? "") >= (b.created_at ?? "") ? a : b,
      );
    },
    [indexes],
  );

  /** Optimistic scope while URL catches up after picker change. */
  const [optimisticAgentId, setOptimisticAgentId] = useState<string | null | undefined>(
    undefined,
  );
  const [optimisticCollectionId, setOptimisticCollectionId] = useState<
    string | null | undefined
  >(undefined);

  useEffect(() => {
    if (optimisticAgentId === undefined && optimisticCollectionId === undefined) return;
    if (
      (selectedAgentId ?? null) === (optimisticAgentId ?? null) &&
      (selectedCollectionId ?? null) === (optimisticCollectionId ?? null)
    ) {
      setOptimisticAgentId(undefined);
      setOptimisticCollectionId(undefined);
    }
  }, [optimisticAgentId, optimisticCollectionId, selectedAgentId, selectedCollectionId]);

  const effectiveAgentId = useMemo((): string | null => {
    if (optimisticAgentId !== undefined) return optimisticAgentId;
    if (selectedAgentId) return selectedAgentId;
    if (selectedIndexId && indexes.length > 0) {
      const idx = indexes.find((i) => i.id === selectedIndexId);
      if (idx?.agent_id) return idx.agent_id;
    }
    return null;
  }, [optimisticAgentId, selectedAgentId, selectedIndexId, indexes]);

  const effectiveCollectionId = useMemo((): string | null => {
    if (optimisticCollectionId !== undefined) return optimisticCollectionId;
    if (selectedCollectionId) return selectedCollectionId;
    if (selectedIndexId && indexes.length > 0) {
      const idx = indexes.find((i) => i.id === selectedIndexId);
      if (idx?.collection_id) return idx.collection_id;
    }
    return null;
  }, [optimisticCollectionId, selectedCollectionId, selectedIndexId, indexes]);

  const scopedSpace = useMemo(() => {
    if (effectiveCollectionId) {
      return {
        key: effectiveCollectionId,
        agentId: null,
        collectionId: effectiveCollectionId,
        label: "Collection",
        kind: "collection" as const,
      };
    }
    return spaces.find((s) => s.agentId === effectiveAgentId) ?? spaces[0];
  }, [spaces, effectiveAgentId, effectiveCollectionId]);

  const spaceIndex = useMemo(
    () => latestFor(scopedSpace?.agentId ?? null, scopedSpace?.collectionId ?? null),
    [latestFor, scopedSpace],
  );

  /** Keep URL index_id and agent_id aligned without undoing an in-flight picker change. */
  useEffect(() => {
    if (!onIndexChange || indexes.length === 0) return;

    const idxFromUrl = selectedIndexId ? indexes.find((i) => i.id === selectedIndexId) : null;
    const indexAgent = idxFromUrl?.agent_id ?? null;
    const indexCollection = idxFromUrl?.collection_id ?? null;
    const urlAgent = selectedAgentId ?? null;
    const urlCollection = selectedCollectionId ?? null;

    if (optimisticAgentId !== undefined || optimisticCollectionId !== undefined) return;

    if (selectedIndexId && urlAgent === null && urlCollection === null && (indexAgent || indexCollection)) {
      onIndexChange(selectedIndexId, indexAgent, indexCollection);
      return;
    }

    if (urlAgent && (indexAgent !== urlAgent || indexCollection)) {
      const corrected = latestFor(urlAgent, null);
      onIndexChange(corrected?.id ?? null, urlAgent, null);
      return;
    }

    if (urlCollection && (indexCollection !== urlCollection || indexAgent)) {
      const corrected = latestFor(null, urlCollection);
      onIndexChange(corrected?.id ?? null, null, urlCollection);
      return;
    }

    if (urlAgent && !selectedIndexId) {
      const corrected = latestFor(urlAgent, null);
      if (corrected) onIndexChange(corrected.id, urlAgent, null);
    }
    if (urlCollection && !selectedIndexId) {
      const corrected = latestFor(null, urlCollection);
      if (corrected) onIndexChange(corrected.id, null, urlCollection);
    }
  }, [
    indexes,
    latestFor,
    onIndexChange,
    optimisticAgentId,
    optimisticCollectionId,
    selectedAgentId,
    selectedCollectionId,
    selectedIndexId,
  ]);

  useEffect(() => {
    onActiveIndexChange?.(spaceIndex);
  }, [spaceIndex, onActiveIndexChange]);

  const handleMemorySpaceChange = useCallback(
    (sel: SourceScopeSelection | null) => {
      const aid = sel?.kind === "agent" ? sel.id : null;
      const cid = sel?.kind === "collection" ? sel.id : null;
      setOptimisticAgentId(aid);
      setOptimisticCollectionId(cid);
      const idx = latestFor(aid, cid);
      onIndexChange?.(idx?.id ?? null, aid, cid);
    },
    [latestFor, onIndexChange],
  );

  const memorySpaceValue = useMemo((): SourceScopeSelection | null => {
    if (effectiveCollectionId) return { kind: "collection", id: effectiveCollectionId };
    if (!effectiveAgentId) return null;
    return { kind: "agent", id: effectiveAgentId };
  }, [effectiveAgentId, effectiveCollectionId]);

  const loadCorpusDelta = useCallback(async () => {
    const aid = scopedSpace?.agentId ?? selectedAgentId ?? null;
    try {
      const qs = aid ? `?agent_id=${encodeURIComponent(aid)}` : "";
      const res = await fetchWithTimeout(`${base}/dashboard${qs}`, {
        cache: "no-store",
        timeoutMs: 15_000,
      });
      const body = (await res.json()) as {
        workspace_compare?: {
          graphrag?: { build_documents?: number; ended_at?: string | null };
          corpus_now?: number;
          stale?: boolean;
        };
        selection?: {
          agent?: {
            compare?: {
              graphrag?: { build_documents?: number; ended_at?: string | null };
              corpus_now?: number;
              stale?: boolean;
            };
          };
        };
      };
      if (!res.ok) {
        setCorpusDelta(null);
        return;
      }
      const c = aid ? body.selection?.agent?.compare : body.workspace_compare;
      if (!c) {
        setCorpusDelta(null);
        return;
      }
      setCorpusDelta({
        buildDocuments: c.graphrag?.build_documents ?? 0,
        corpusNow: c.corpus_now ?? 0,
        endedAt: c.graphrag?.ended_at,
        stale: c.stale,
      });
    } catch {
      setCorpusDelta(null);
    }
  }, [base, scopedSpace?.agentId, selectedAgentId]);

  useEffect(() => {
    if (spaceIndex?.status === "ready") void loadCorpusDelta();
    else setCorpusDelta(null);
  }, [spaceIndex?.status, spaceIndex?.id, loadCorpusDelta]);

  useEffect(() => {
    const active = indexes.filter((i) => i.status === "pending" || i.status === "running");
    if (active.length === 0) return;
    let opened = false;
    for (const idx of active) {
      const jobId = graphragJobId(idx.id);
      if (registeredBuildJobsRef.current.has(jobId)) continue;
      registeredBuildJobsRef.current.add(jobId);
      registerActiveJob(jobId, workspaceId, null, "graphrag_index");
      opened = true;
    }
    if (opened) requestOpenLogConsole();
  }, [indexes, registerActiveJob, requestOpenLogConsole, workspaceId]);

  useEffect(() => {
    for (const idx of indexes) {
      const jobId = graphragJobId(idx.id);
      const prevStatus = indexStatusRef.current.get(idx.id);
      const reason = (idx.failure_reason ?? "").trim();

      if (idx.status === "failed") {
        unregisterActiveJob(jobId);
        registeredBuildJobsRef.current.delete(jobId);

        const superseded = reason.toLowerCase().includes("superseded");
        const watchedBuild = prevStatus === "pending" || prevStatus === "running";
        const userInitiated = userTriggeredBuildRef.current.has(jobId);
        if (
          !superseded &&
          userInitiated &&
          watchedBuild &&
          !failedNotifiedRef.current.has(idx.id)
        ) {
          failedNotifiedRef.current.add(idx.id);
          toast({
            variant: "error",
            message: "GraphRAG index build failed",
            description: reason || "Restart the build from Graph.",
          });
        }
      } else if (idx.status === "ready") {
        unregisterActiveJob(jobId);
        registeredBuildJobsRef.current.delete(jobId);
      }

      indexStatusRef.current.set(idx.id, idx.status);
    }
  }, [indexes, toast, unregisterActiveJob]);

  const watchIndex = useCallback(
    (index: GraphragIndexRow, label: string) => {
      const jobId = graphragJobId(index.id);
      userTriggeredBuildRef.current.add(jobId);
      registerActiveJob(jobId, workspaceId, null, "graphrag_index");
      requestOpenLogConsole();
      toast({
        variant: "success",
        message: "Subscribed to GraphRAG build log",
        description: label,
      });
    },
    [registerActiveJob, requestOpenLogConsole, toast, workspaceId],
  );

  const buildTargetSpace = scopedSpace ?? spaces[0] ?? null;

  const build = useCallback(
    async (space: Space) => {
      setBusyKey(space.key);
      let started = false;
      try {
        const result = await startGraphragIndex(workspaceId, {
          agentId: space.agentId,
          collectionId: space.collectionId,
          maxDocs,
        });
        if (!result.ok) {
          toast({
            variant: "error",
            message: result.message,
            description: result.description,
          });
          return;
        }
        started = true;
        if (result.jobId) {
          userTriggeredBuildRef.current.add(result.jobId);
          registerActiveJob(
            result.jobId,
            workspaceId,
            space.agentId ?? space.collectionId,
            "graphrag_index",
          );
          requestOpenLogConsole();
        }
        toast({ variant: "success", message: `GraphRAG index started for ${space.label}` });
      } finally {
        setBusyKey(null);
      }
      if (started) void loadIndexes();
    },
    [maxDocs, toast, loadIndexes, registerActiveJob, requestOpenLogConsole, workspaceId],
  );

  useEffect(() => {
    if (!onRegisterBuild) return;
    onRegisterBuild(() => {
      if (buildTargetSpace) void build(buildTargetSpace);
    });
  }, [build, buildTargetSpace, onRegisterBuild]);

  if (compact) {
    const status = spaceIndex?.status ?? "none";
    const stats = (spaceIndex?.stats ?? {}) as Record<string, number>;
    const active = status === "pending" || status === "running";
    return (
      <div className="relative z-30 flex flex-wrap items-end gap-2 overflow-visible rounded-md border border-border bg-secondary/30 px-3 py-2">
        <div className="relative z-30 min-w-[14rem] max-w-[20rem] flex-1">
          <SourceScopeFilter
            workspaceId={workspaceId}
            value={memorySpaceValue}
            onChange={handleMemorySpaceChange}
            label="Memory space"
            includeDocuments={false}
            includeWholeWorkspace
          />
        </div>
        {status !== "none" ? (
          <Badge variant={statusVariant(status)}>{status}</Badge>
        ) : null}
        {status === "ready" ? (
          <span className="text-caption text-muted-foreground">
            {stats.entities ?? 0} ent · {stats.relationships ?? 0} rel
            {corpusDelta && (corpusDelta.buildDocuments > 0 || corpusDelta.corpusNow > 0) ? (
              <>
                {" · "}Built from {corpusDelta.buildDocuments} docs
                {corpusDelta.endedAt
                  ? ` on ${new Date(corpusDelta.endedAt).toLocaleDateString()}`
                  : ""}
                {" · "}corpus now {corpusDelta.corpusNow}
                {corpusDelta.stale ? (
                  <span className="text-caution"> (corpus grew)</span>
                ) : null}
              </>
            ) : null}
          </span>
        ) : null}
        <label className="flex items-center gap-1 text-caption text-muted-foreground">
          Max docs
          <Input
            type="number"
            min={4}
            max={5000}
            value={maxDocs}
            onChange={(e) => setMaxDocs(Number(e.target.value) || 200)}
            className="h-7 w-20"
          />
        </label>
        {spaceIndex && (active || status === "failed" || status === "ready") ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => watchIndex(spaceIndex, scopedSpace?.label ?? "index")}
          >
            Log
          </Button>
        ) : null}
        <Button
          size="sm"
          variant={status === "ready" ? "outline" : "default"}
          disabled={!buildTargetSpace || busyKey === buildTargetSpace?.key}
          onClick={() => buildTargetSpace && void build(buildTargetSpace)}
        >
          {buildTargetSpace && busyKey === buildTargetSpace.key
            ? "Starting…"
            : active
              ? "Start new build"
              : status === "ready" || status === "failed"
                ? "Rebuild"
                : "Build"}
        </Button>
        <Link href="/pipelines" className="text-caption text-primary hover:underline">
          Pipelines
        </Link>
        {loading ? <span className="text-caption text-muted-foreground">…</span> : null}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <table className="w-full text-p">
        <thead className="bg-secondary/40 text-caption text-muted-foreground">
          <tr>
            <th className="px-4 py-2 text-left font-medium">Memory space</th>
            <th className="px-4 py-2 text-left font-medium">Status</th>
            <th className="px-4 py-2 text-left font-medium">Stats</th>
            <th className="px-4 py-2 text-right font-medium">Action</th>
          </tr>
        </thead>
        <tbody>
          {spaces.map((s) => {
            const idx = latestFor(s.agentId);
            const status = idx?.status ?? "none";
            const stats = (idx?.stats ?? {}) as Record<string, number>;
            const active = status === "pending" || status === "running";
            return (
              <tr key={s.key} className={cn("border-t border-border", active && "bg-caution/5")}>
                <td className="px-4 py-2">
                  <span className="text-foreground">{s.label}</span>
                  {s.kind !== "workspace" ? (
                    <Badge variant="outline" className="ml-2">
                      {s.kind}
                    </Badge>
                  ) : null}
                </td>
                <td className="px-4 py-2">
                  {status === "none" ? (
                    <span className="text-muted-foreground">not built</span>
                  ) : (
                    <Badge variant={statusVariant(status)}>{status}</Badge>
                  )}
                </td>
                <td className="px-4 py-2 text-caption text-muted-foreground">
                  {status === "ready"
                    ? `${stats.entities ?? 0} entities · ${stats.relationships ?? 0} rels · ${stats.community_reports ?? 0} reports`
                    : "—"}
                </td>
                <td className="px-4 py-2 text-right">
                  <div className="flex items-center justify-end gap-2">
                    {idx ? (
                      <Button size="sm" variant="outline" onClick={() => watchIndex(idx, s.label)}>
                        Watch log
                      </Button>
                    ) : null}
                    <Button
                      size="sm"
                      variant={status === "ready" ? "outline" : "default"}
                      disabled={busyKey === s.key}
                      onClick={() => void build(s)}
                    >
                      {busyKey === s.key
                        ? "Starting…"
                        : active
                          ? "Start new build"
                          : status === "ready" || status === "failed"
                            ? "Rebuild"
                            : "Build index"}
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
