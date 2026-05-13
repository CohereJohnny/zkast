"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";

import { DocumentsPanel } from "@/components/documents-panel";
import { GraphWorkspacePanel } from "@/components/graph-workspace-panel";
import { JobLogConsole } from "@/components/job-log-console";

const STORAGE_KEY = "zkast.workspace.documentsCollapsed";

type Props = {
  workspaceId: string;
  children: ReactNode;
};

function CollapseRail({ onExpand }: { onExpand: () => void }) {
  return (
    <button
      type="button"
      onClick={onExpand}
      title="Expand documents panel"
      aria-label="Expand documents panel"
      aria-expanded={false}
      className="flex h-full w-full flex-col items-center justify-start gap-3 rounded-lg border border-border-subtle bg-surface/80 py-3 text-caption text-muted hover:bg-surface hover:text-secondary"
    >
      <span aria-hidden="true" className="text-body leading-none">›</span>
      <span
        aria-hidden="true"
        className="whitespace-nowrap text-[10px] uppercase tracking-wider [writing-mode:vertical-rl]"
      >
        Documents
      </span>
    </button>
  );
}

function CollapseHeaderButton({ onCollapse }: { onCollapse: () => void }) {
  return (
    <button
      type="button"
      onClick={onCollapse}
      title="Collapse documents panel"
      aria-label="Collapse documents panel"
      aria-expanded
      className="ml-auto rounded border border-border-subtle px-1.5 py-0.5 text-caption text-muted hover:bg-surface hover:text-secondary"
    >
      <span aria-hidden="true">‹</span>
    </button>
  );
}

/**
 * Three-column shell by default (documents peek | main | graph). On `/documents`,
 * the main column already hosts a full DocumentsPanel — hide the duplicate column.
 *
 * The documents area can be collapsed to a thin rail so the graph and its
 * selection panel can use the rest of the row.
 */
export function WorkspaceMainGrid({ workspaceId, children }: Props) {
  const pathname = usePathname();
  const isDocumentsRoute = pathname === "/documents";
  // The main column on /graph is already a full graph view; don't render the
  // right-rail mini graph next to it.
  const showRailGraph = pathname !== "/graph";
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      if (window.localStorage.getItem(STORAGE_KEY) === "1") setCollapsed(true);
    } catch {
      /* ignore */
    }
  }, []);

  const toggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  let gridClass: string;
  if (isDocumentsRoute) {
    gridClass = collapsed
      ? "grid min-h-[480px] flex-1 grid-cols-1 gap-2 lg:grid-cols-[2.25rem_minmax(0,1fr)]"
      : "grid min-h-[480px] flex-1 grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]";
  } else if (!showRailGraph) {
    // /graph route: documents peek (or rail) | main full-bleed graph
    gridClass = collapsed
      ? "grid min-h-[480px] flex-1 grid-cols-1 gap-2 lg:grid-cols-[2.25rem_minmax(0,1fr)]"
      : "grid min-h-[480px] flex-1 grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,3fr)]";
  } else {
    gridClass = collapsed
      ? "grid min-h-[480px] flex-1 grid-cols-1 gap-2 lg:grid-cols-[2.25rem_minmax(0,1fr)_minmax(0,1.6fr)]"
      : "grid min-h-[480px] flex-1 grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)_minmax(0,1fr)]";
  }

  return (
    <div className="flex min-h-[calc(100vh-2rem)] flex-col gap-4">
      <div className={gridClass}>
        {isDocumentsRoute ? (
          collapsed ? (
            <>
              <CollapseRail onExpand={toggle} />
              <GraphWorkspacePanel workspaceId={workspaceId} />
            </>
          ) : (
            <>
              <section
                id="main-content"
                tabIndex={-1}
                aria-label="Documents"
                className="flex min-h-0 min-h-[320px] flex-col gap-3 rounded-lg border border-border-strong bg-surface p-4 outline-none"
              >
                <div className="flex items-center gap-2">
                  <CollapseHeaderButton onCollapse={toggle} />
                </div>
                {/* Documents takes natural height; the log fills the rest
                    of the column. ``min-h-0`` on both is required for
                    nested flex children to scroll instead of overflow. */}
                <div className="min-h-0 flex-1 overflow-auto">{children}</div>
                <JobLogConsole />
              </section>
              <GraphWorkspacePanel workspaceId={workspaceId} />
            </>
          )
        ) : (
          <>
            {collapsed ? (
              <CollapseRail onExpand={toggle} />
            ) : (
              <section
                aria-label="Documents"
                className="flex min-h-0 min-h-[480px] flex-col gap-3 rounded-lg border border-border-subtle bg-surface/80 p-4"
              >
                <div className="flex items-center gap-2">
                  <p className="text-caption font-medium text-secondary">Documents</p>
                  <CollapseHeaderButton onCollapse={toggle} />
                </div>
                {/* The DocumentsPanel scrolls internally; the log sits
                    below it and the log's expanded body flex-grows into
                    any remaining vertical room. */}
                <div className="min-h-0 flex-1 overflow-hidden">
                  <DocumentsPanel workspaceId={workspaceId} variant="compact" />
                </div>
                <JobLogConsole />
              </section>
            )}
            <section
              id="main-content"
              tabIndex={-1}
              aria-label="Main workspace panel"
              className="flex min-h-[320px] flex-col rounded-lg border border-border-strong bg-surface outline-none"
            >
              {children}
            </section>
            {showRailGraph ? <GraphWorkspacePanel workspaceId={workspaceId} /> : null}
          </>
        )}
      </div>
    </div>
  );
}
