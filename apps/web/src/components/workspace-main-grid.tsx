"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { GraphWorkspacePanel } from "@/components/graph-workspace-panel";
import { JobLogConsole } from "@/components/job-log-console";
import { cn } from "@/lib/utils";

const STORAGE_KEY_DOCS = "zkast.workspace.documentsCollapsed";
const STORAGE_KEY_GRAPH = "zkast.workspace.graphCollapsed";

type Props = {
  workspaceId: string;
  children: ReactNode;
};

type Side = "left" | "right";

function CollapseRail({
  onExpand,
  label,
  side,
}: {
  onExpand: () => void;
  label: string;
  side: Side;
}) {
  // Chevron points "into" the rail: left rail expands to the right (›),
  // right rail expands to the left (‹).
  const chevron = side === "left" ? "›" : "‹";
  return (
    <button
      type="button"
      onClick={onExpand}
      title={`Expand ${label.toLowerCase()} panel`}
      aria-label={`Expand ${label.toLowerCase()} panel`}
      aria-expanded={false}
      className="flex h-full w-full cursor-pointer flex-col items-center justify-start gap-3 rounded-lg border border-border-subtle bg-surface/80 py-3 text-caption text-muted transition-colors duration-150 hover:bg-surface hover:text-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
    >
      <span aria-hidden="true" className="text-body leading-none">
        {chevron}
      </span>
      <span
        aria-hidden="true"
        className="whitespace-nowrap text-[10px] uppercase tracking-wider [writing-mode:vertical-rl]"
      >
        {label}
      </span>
    </button>
  );
}

function CollapseHeaderButton({
  onCollapse,
  label,
  side,
}: {
  onCollapse: () => void;
  label: string;
  side: Side;
}) {
  // Chevron points toward the rail it collapses to: left panel collapses
  // toward the left edge (‹); right panel collapses toward the right edge (›).
  const chevron = side === "left" ? "‹" : "›";
  return (
    <button
      type="button"
      onClick={onCollapse}
      title={`Collapse ${label.toLowerCase()} panel`}
      aria-label={`Collapse ${label.toLowerCase()} panel`}
      aria-expanded
      className="ml-auto cursor-pointer rounded border border-border-subtle px-1.5 py-0.5 text-caption text-muted transition-colors duration-150 hover:bg-surface hover:text-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
    >
      <span aria-hidden="true">{chevron}</span>
    </button>
  );
}

/**
 * On `/documents`, the shell uses a collapsible documents/library column plus
 * pipeline log on the left and the mini graph rail on the right. On
 * `/conversations` and `/agents/[id]`, the main column mirrors that pattern
 * (scrollable library + pipeline log); imports and Dream runs stream into the
 * same log console.
 * Elsewhere, layout is main workspace plus graph rail (two columns); `/graph`
 * is main-only.
 *
 * The documents column can collapse to a thin rail so the graph rail can grow.
 */
export function WorkspaceMainGrid({ workspaceId, children }: Props) {
  const pathname = usePathname();
  const isDocumentsRoute = pathname === "/documents";
  const isConversationsRoute = pathname === "/conversations";
  const isJobsRoute = pathname === "/jobs";
  const isAgentDetailRoute = /^\/agents\/[^/]+$/.test(pathname);
  const dockJobLog = isConversationsRoute || isJobsRoute || isAgentDetailRoute;
  // The main column on /graph is already a full graph view; don't render the
  // right-rail mini graph next to it.
  const showRailGraph = pathname !== "/graph";
  const [docsCollapsed, setDocsCollapsed] = useState(false);
  const [graphCollapsed, setGraphCollapsed] = useState(false);

  useEffect(() => {
    try {
      if (window.localStorage.getItem(STORAGE_KEY_DOCS) === "1") {
        setDocsCollapsed(true);
      }
      if (window.localStorage.getItem(STORAGE_KEY_GRAPH) === "1") {
        setGraphCollapsed(true);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const toggleDocs = () => {
    setDocsCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(STORAGE_KEY_DOCS, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  const toggleGraph = () => {
    setGraphCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(STORAGE_KEY_GRAPH, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  // Grid templates are static literal strings (per combination) so that
  // Tailwind's JIT scanner can detect them. Dynamic template-literal
  // composition would silently drop these arbitrary-value classes.
  const GRID_BASE = "grid min-h-[480px] flex-1 grid-cols-1 gap-2";

  let gridClass: string;
  if (isDocumentsRoute) {
    // /documents: library + job log column; collapsible graph rail on the right.
    if (docsCollapsed && graphCollapsed) {
      gridClass = `${GRID_BASE} lg:grid-cols-[2.25rem_minmax(0,1fr)_2.25rem]`;
    } else if (docsCollapsed) {
      gridClass = `${GRID_BASE} lg:grid-cols-[2.25rem_minmax(0,1fr)]`;
    } else if (graphCollapsed) {
      gridClass = `${GRID_BASE} lg:grid-cols-[minmax(0,1fr)_2.25rem]`;
    } else {
      gridClass = `${GRID_BASE} lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]`;
    }
  } else if (!showRailGraph) {
    // /graph: full-width graph in main — no side rails from this shell.
    gridClass = `${GRID_BASE} lg:grid-cols-[minmax(0,1fr)]`;
  } else {
    // Default: main workspace | graph rail.
    if (graphCollapsed) {
      gridClass = `${GRID_BASE} lg:grid-cols-[minmax(0,1fr)_2.25rem]`;
    } else {
      gridClass = `${GRID_BASE} lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]`;
    }
  }

  // ``h-[calc(100vh-2rem)]`` instead of ``min-h`` — children need a
  // **definite** parent height for ``flex-1`` and ``height:100%`` to
  // compute. Without it the grid row collapses to ``min-h-[480px]`` and
  // the graph canvas + embedded log can't size themselves correctly.
  // ``overflow-hidden`` keeps any child overflow inside the panel
  // (which scrolls via its own ``overflow-auto``) instead of pushing
  // the whole page taller — the regression we saw with the log open.
  const renderGraphCell = () => {
    if (!showRailGraph) return null;
    return graphCollapsed ? (
      <CollapseRail onExpand={toggleGraph} label="Graph" side="right" />
    ) : (
      <GraphWorkspacePanel workspaceId={workspaceId} onCollapse={toggleGraph} />
    );
  };

  return (
    <div className="flex h-[calc(100vh-2rem)] flex-col gap-4 overflow-hidden">
      <div className={gridClass}>
        {isDocumentsRoute ? (
          <>
            {docsCollapsed ? (
              <CollapseRail
                onExpand={toggleDocs}
                label="Documents"
                side="left"
              />
            ) : (
              <section
                id="main-content"
                tabIndex={-1}
                aria-label="Documents"
                className="flex min-h-0 flex-col gap-3 overflow-hidden rounded-lg border border-border-strong bg-surface p-4 outline-none"
              >
                <div className="flex items-center gap-2">
                  <CollapseHeaderButton
                    onCollapse={toggleDocs}
                    label="Documents"
                    side="left"
                  />
                </div>
                {/* Library panel takes the bulk of the column and scrolls
                    inside; the log is bounded below — when open it
                    shares the column ~50/50, when closed it shrinks to
                    a thin header. */}
                <div className="min-h-0 flex-1 overflow-auto">{children}</div>
                <JobLogConsole />
              </section>
            )}
            {/* Both rails collapsed: middle cell is an expand spacer. */}
            {docsCollapsed && graphCollapsed ? (
              <div aria-hidden="true" />
            ) : null}
            {renderGraphCell()}
          </>
        ) : (
          <>
            <section
              id="main-content"
              tabIndex={-1}
              aria-label={
                isConversationsRoute
                  ? "Conversations"
                  : isJobsRoute
                    ? "Jobs"
                    : isAgentDetailRoute
                      ? "Agent conversations"
                      : "Main workspace panel"
              }
              className={cn(
                "flex min-h-0 flex-col rounded-lg border border-border-strong bg-surface outline-none",
                dockJobLog ? "gap-3 overflow-hidden p-4" : "overflow-auto",
              )}
            >
              {dockJobLog ? (
                <>
                  {/* Same split as Documents column: scroll library; dock log below
                      so ingestion traces stay visible while browsing imports. */}
                  <div className="min-h-0 flex-1 overflow-auto">{children}</div>
                  <JobLogConsole />
                </>
              ) : (
                children
              )}
            </section>
            {renderGraphCell()}
          </>
        )}
      </div>
    </div>
  );
}
