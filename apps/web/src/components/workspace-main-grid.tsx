"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

import { DocumentsPanel } from "@/components/documents-panel";

type Props = {
  workspaceId: string;
  children: ReactNode;
};

/**
 * Three-column shell by default (documents peek | main | graph). On `/documents`,
 * the main column already hosts a full DocumentsPanel — hide the duplicate column.
 */
export function WorkspaceMainGrid({ workspaceId, children }: Props) {
  const pathname = usePathname();
  const isDocumentsRoute = pathname === "/documents";

  const gridClass = isDocumentsRoute
    ? "grid min-h-[480px] flex-1 grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]"
    : "grid min-h-[480px] flex-1 grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)_minmax(0,1fr)]";

  return (
    <div className="flex min-h-[calc(100vh-2rem)] flex-col gap-4">
      <div className={gridClass}>
        {!isDocumentsRoute ? (
          <section
            aria-label="Documents"
            className="flex min-h-[480px] flex-col rounded-lg border border-border-subtle bg-surface/80 p-4"
          >
            <DocumentsPanel workspaceId={workspaceId} variant="compact" />
          </section>
        ) : null}
        <section
          id="main-content"
          tabIndex={-1}
          aria-label="Main workspace panel"
          className="flex min-h-[320px] flex-col rounded-lg border border-border-strong bg-surface outline-none"
        >
          {children}
        </section>
        <section
          aria-label="Graph panel placeholder"
          className="rounded-lg border border-border-subtle bg-surface/80 p-4 text-caption text-muted"
        >
          <p className="text-title-3 text-secondary">Graph panel</p>
          <p className="mt-2">Working graph canvas will anchor here by default.</p>
        </section>
      </div>
    </div>
  );
}
