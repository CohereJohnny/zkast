"use client";

import { BookOpen, FileText, RefreshCw, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AgentPicker } from "@/components/filters/agent-picker";
import { useToast } from "@/components/feedback-provider";
import { WikiJobStatus } from "@/components/wiki-job-status";
import { readApiErrorMessage } from "@/lib/api-error-message";
import { useJobEvents } from "@/lib/job-events";
import { cn } from "@/lib/utils";

/**
 * Sprint E — LLM Wiki memory surface.
 *
 * Layout:
 *
 *  - Top toolbar: scope selector (workspace vs North agent), Generate button,
 *    current Wiki job status.
 *  - Two-column body:
 *      Left: page list grouped by page type (synthesis, topic, entity,
 *      comparison, source_summary, index, changelog).
 *      Right: page reader (body + citation sidebar).
 *  - The docked Pipeline log (mounted by `WorkspaceMainGrid` on `/wiki`)
 *    streams verbose generation telemetry while a wiki job is running.
 */

type WikiSpace = {
  id: string;
  workspace_id: string;
  agent_id?: string | null;
  scope_kind: "workspace" | "agent" | "document" | "conversation";
  scope_target_id?: string | null;
  name: string;
  status: "empty" | "generating" | "ready" | "stale" | "failed";
  last_generated_at?: string | null;
  page_count?: number;
};

type WikiPage = {
  id: string;
  wiki_space_id: string;
  slug: string;
  title: string;
  page_type:
    | "source_summary"
    | "entity"
    | "topic"
    | "synthesis"
    | "comparison"
    | "index"
    | "changelog";
  summary?: string | null;
  status: string;
  body?: string;
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
};

type WikiSource = {
  id: string;
  source_kind: string;
  source_id: string;
  quote?: string | null;
  weight?: number | null;
};

const PAGE_TYPE_LABELS: Record<WikiPage["page_type"], string> = {
  synthesis: "Synthesis",
  topic: "Topics",
  entity: "Entities",
  comparison: "Comparisons",
  source_summary: "Source summaries",
  index: "Index",
  changelog: "Changelog",
};

const PAGE_TYPE_ORDER: WikiPage["page_type"][] = [
  "synthesis",
  "index",
  "topic",
  "entity",
  "comparison",
  "source_summary",
  "changelog",
];

export function WikiPanel({
  workspaceId,
  initialSpaceId,
  initialSlug,
}: {
  workspaceId: string;
  initialSpaceId?: string | null;
  initialSlug?: string | null;
}) {
  const toast = useToast();
  const { registerActiveJob, requestOpenLogConsole } = useJobEvents();

  const [spaces, setSpaces] = useState<WikiSpace[]>([]);
  const [spacesLoading, setSpacesLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeSpaceId, setActiveSpaceId] = useState<string | null>(
    initialSpaceId ?? null,
  );
  const [pages, setPages] = useState<WikiPage[]>([]);
  const [pagesLoading, setPagesLoading] = useState(false);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(
    initialSlug ?? null,
  );
  const [selectedPage, setSelectedPage] = useState<WikiPage | null>(null);
  const [selectedSources, setSelectedSources] = useState<WikiSource[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [agentScope, setAgentScope] = useState<string>("");

  const reloadSpaces = useCallback(async () => {
    setSpacesLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/wiki-spaces`, {
        cache: "no-store",
      });
      const body = (await res.json().catch(() => ({}))) as {
        items?: WikiSpace[];
        error?: { message?: string };
      };
      if (!res.ok) {
        setError(readApiErrorMessage(body, `HTTP ${res.status}`));
        return;
      }
      setSpaces(body.items ?? []);
    } finally {
      setSpacesLoading(false);
    }
  }, [workspaceId]);

  const reloadPages = useCallback(
    async (spaceId: string) => {
      setPagesLoading(true);
      try {
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/wiki-spaces/${encodeURIComponent(spaceId)}`,
          { cache: "no-store" },
        );
        const body = (await res.json().catch(() => ({}))) as {
          space?: WikiSpace;
          pages?: WikiPage[];
        };
        setPages(body.pages ?? []);
      } finally {
        setPagesLoading(false);
      }
    },
    [workspaceId],
  );

  useEffect(() => {
    void reloadSpaces();
  }, [reloadSpaces]);

  useEffect(() => {
    if (activeSpaceId) {
      void reloadPages(activeSpaceId);
    } else {
      setPages([]);
      setSelectedPage(null);
      setSelectedSlug(null);
    }
  }, [activeSpaceId, reloadPages]);

  useEffect(() => {
    if (!activeSpaceId || !selectedSlug) {
      setSelectedPage(null);
      setSelectedSources([]);
      return;
    }
    let cancelled = false;
    void (async () => {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/wiki-spaces/${encodeURIComponent(activeSpaceId)}/pages/${encodeURIComponent(selectedSlug)}`,
        { cache: "no-store" },
      );
      const body = (await res.json().catch(() => ({}))) as {
        page?: WikiPage;
        sources?: WikiSource[];
      };
      if (cancelled) return;
      setSelectedPage(body.page ?? null);
      setSelectedSources(body.sources ?? []);
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, activeSpaceId, selectedSlug]);

  const activeSpace = useMemo(
    () => spaces.find((s) => s.id === activeSpaceId) ?? null,
    [spaces, activeSpaceId],
  );

  const ensureScopedSpace = useCallback(async (): Promise<WikiSpace | null> => {
    const trimmed = agentScope.trim();
    const payload = trimmed
      ? { scope_kind: "agent" as const, agent_id: trimmed }
      : { scope_kind: "workspace" as const };
    const res = await fetch(`/api/v1/workspaces/${workspaceId}/wiki-spaces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = (await res.json().catch(() => ({}))) as
      | (WikiSpace & { error?: { message?: string } })
      | { error?: { message?: string } };
    if (!res.ok || !("id" in body)) {
      const msg = readApiErrorMessage(body as Record<string, unknown>, `HTTP ${res.status}`);
      toast({ variant: "error", message: "Could not prepare wiki space", description: msg });
      return null;
    }
    const space = body as WikiSpace;
    setActiveSpaceId(space.id);
    await reloadSpaces();
    return space;
  }, [agentScope, workspaceId, reloadSpaces, toast]);

  const onGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    try {
      const space = activeSpace ?? (await ensureScopedSpace());
      if (!space) return;
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/wiki-spaces/${encodeURIComponent(space.id)}/generate`,
        { method: "POST" },
      );
      const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (!res.ok) {
        const msg = readApiErrorMessage(body, `HTTP ${res.status}`);
        setError(msg);
        toast({ variant: "error", message: "Wiki job failed to queue", description: msg });
        return;
      }
      const jid = typeof body.job_id === "string" ? body.job_id : null;
      if (jid) {
        setActiveJobId(jid);
        registerActiveJob(jid, workspaceId, null, "wiki_generation");
        requestOpenLogConsole();
        toast({
          variant: "success",
          message: "Wiki generation queued",
          description: "Watch progress in the pipeline log below.",
        });
      }
    } finally {
      setGenerating(false);
    }
  }, [
    activeSpace,
    ensureScopedSpace,
    workspaceId,
    registerActiveJob,
    requestOpenLogConsole,
    toast,
  ]);

  const onJobDone = useCallback(
    (status: "succeeded" | "failed") => {
      if (status === "succeeded") {
        toast({
          variant: "success",
          message: "Wiki ready",
          description: "Pages were generated for the selected scope.",
        });
        if (activeSpaceId) void reloadPages(activeSpaceId);
        void reloadSpaces();
      } else {
        toast({
          variant: "error",
          message: "Wiki generation failed",
          description: "See the pipeline log for details.",
        });
      }
    },
    [activeSpaceId, reloadPages, reloadSpaces, toast],
  );

  const groupedPages = useMemo(() => {
    const groups = new Map<WikiPage["page_type"], WikiPage[]>();
    for (const p of pages) {
      const arr = groups.get(p.page_type) ?? [];
      arr.push(p);
      groups.set(p.page_type, arr);
    }
    return groups;
  }, [pages]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <header className="flex flex-wrap items-center gap-2">
        <BookOpen className="h-5 w-5 text-muted" strokeWidth={1.5} aria-hidden />
        <h1 className="text-title-2 text-primary">Wiki</h1>
        <p className="text-caption text-muted">
          LLM-generated, citation-backed pages compiled from your atomic notes.
        </p>
      </header>

      {error ? (
        <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-body text-destructive">
          {error}
        </p>
      ) : null}

      <section
        className="flex flex-wrap items-end gap-3 rounded-lg border border-border-subtle bg-surface px-3 py-2"
        aria-label="Wiki scope and actions"
      >
        <label className="block text-caption text-muted">
          Wiki space
          <select
            className="mt-1 block w-64 rounded-md border border-border-strong bg-surface px-2 py-1 text-body text-secondary"
            value={activeSpaceId ?? ""}
            onChange={(e) => setActiveSpaceId(e.target.value || null)}
          >
            <option value="">— select or create —</option>
            {spaces.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
                {s.scope_kind === "agent" ? " (agent)" : ""} · {s.status}
              </option>
            ))}
          </select>
        </label>
        <div className="min-w-[220px] flex-1">
          <AgentPicker
            workspaceId={workspaceId}
            value={agentScope}
            onChange={setAgentScope}
            label="Generate scoped to agent (optional)"
            placeholder="All notes (workspace-wide)"
          />
        </div>
        <button
          type="button"
          onClick={() => void onGenerate()}
          disabled={generating}
          className={cn(
            "inline-flex items-center gap-1 rounded-md border border-border-subtle px-3 py-1.5 text-body text-secondary",
            "hover:bg-surface-raised hover:text-primary disabled:opacity-50",
          )}
        >
          <Sparkles className="h-4 w-4" strokeWidth={1.5} aria-hidden />
          {activeSpace ? "Generate" : "Create and generate"}
        </button>
        <button
          type="button"
          onClick={() => {
            void reloadSpaces();
            if (activeSpaceId) void reloadPages(activeSpaceId);
          }}
          className="inline-flex items-center gap-1 rounded-md border border-border-subtle px-3 py-1.5 text-body text-secondary hover:bg-surface-raised hover:text-primary"
        >
          <RefreshCw className="h-4 w-4" strokeWidth={1.5} aria-hidden />
          Refresh
        </button>
      </section>

      <WikiJobStatus
        workspaceId={workspaceId}
        jobId={activeJobId}
        onDone={onJobDone}
      />

      {spacesLoading ? (
        <p className="text-caption text-muted" role="status">
          Loading wiki spaces…
        </p>
      ) : null}

      {!spacesLoading && spaces.length === 0 ? (
        <div className="rounded-lg border border-border-subtle bg-surface px-4 py-6 text-body text-muted">
          <p>
            No wiki spaces yet. Click <strong>Create and generate</strong> to
            compile a workspace-wide wiki from your atomic notes, or pick a
            North agent to generate a scoped wiki.
          </p>
        </div>
      ) : null}

      {activeSpace ? (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 md:grid-cols-[260px_1fr]">
          <aside
            aria-label="Wiki page list"
            className="min-h-0 overflow-auto rounded-lg border border-border-subtle bg-surface px-2 py-2"
          >
            {pagesLoading ? (
              <p className="px-2 py-1 text-caption text-muted">Loading pages…</p>
            ) : null}
            {pages.length === 0 && !pagesLoading ? (
              <p className="px-2 py-1 text-caption text-muted">
                No pages yet. Generate to populate.
              </p>
            ) : null}
            {PAGE_TYPE_ORDER.map((pt) => {
              const group = groupedPages.get(pt) ?? [];
              if (group.length === 0) return null;
              return (
                <section key={pt} className="mb-2">
                  <p className="px-2 py-1 text-[10px] uppercase tracking-wider text-muted">
                    {PAGE_TYPE_LABELS[pt]}
                  </p>
                  <ul>
                    {group.map((p) => {
                      const active = p.slug === selectedSlug;
                      return (
                        <li key={p.id}>
                          <button
                            type="button"
                            onClick={() => setSelectedSlug(p.slug)}
                            className={cn(
                              "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-caption",
                              active
                                ? "bg-accent-primary/15 text-primary"
                                : "text-secondary hover:bg-surface-raised hover:text-primary",
                            )}
                          >
                            <FileText
                              className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted"
                              strokeWidth={1.5}
                              aria-hidden
                            />
                            <span className="min-w-0">
                              <span className="block truncate text-body">{p.title}</span>
                              {p.summary ? (
                                <span className="block truncate text-caption text-muted">
                                  {p.summary}
                                </span>
                              ) : null}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
          </aside>

          <section
            aria-label="Wiki page reader"
            className="min-h-0 overflow-auto rounded-lg border border-border-subtle bg-surface px-4 py-4"
          >
            {!selectedPage ? (
              <p className="text-caption text-muted">
                Select a page on the left to read its content.
              </p>
            ) : (
              <div className="grid min-h-0 grid-cols-1 gap-4 xl:grid-cols-[1fr_240px]">
                <article className="prose prose-invert max-w-none">
                  <header className="mb-3">
                    <p className="text-caption uppercase tracking-wider text-muted">
                      {PAGE_TYPE_LABELS[selectedPage.page_type] ?? selectedPage.page_type}
                    </p>
                    <h2 className="text-title-2 text-primary">{selectedPage.title}</h2>
                    {selectedPage.summary ? (
                      <p className="text-caption text-muted">{selectedPage.summary}</p>
                    ) : null}
                  </header>
                  <pre className="whitespace-pre-wrap break-words rounded-md border border-border-subtle bg-canvas px-3 py-3 text-body text-primary">
                    {selectedPage.body ?? ""}
                  </pre>
                </article>
                <aside
                  aria-label="Page citations"
                  className="rounded-md border border-border-subtle bg-canvas px-3 py-3 text-caption"
                >
                  <p className="text-[10px] uppercase tracking-wider text-muted">
                    Citations ({selectedSources.length})
                  </p>
                  {selectedSources.length === 0 ? (
                    <p className="mt-2 text-muted">No citations recorded.</p>
                  ) : (
                    <ul className="mt-2 space-y-2">
                      {selectedSources.map((src) => (
                        <li key={src.id} className="rounded border border-border-subtle bg-surface px-2 py-1.5">
                          <p className="font-mono text-[10px] uppercase text-muted">
                            {src.source_kind}
                          </p>
                          <p className="truncate font-mono text-caption text-secondary" title={src.source_id}>
                            {src.source_id}
                          </p>
                          {src.quote ? (
                            <p className="mt-1 text-caption text-muted">{src.quote}</p>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </aside>
              </div>
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}
