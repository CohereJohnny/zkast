"use client";

import Link from "next/link";
import { useState } from "react";

import type { CitationSource } from "@/lib/chat-stream";

/**
 * Sprint 6 — inline citation marker rendered inside assistant message text.
 *
 * Renders as a small superscript `[N]` chip. Hover (or focus) pops a card
 * showing each source the citation references — kind, identifier, and a
 * short excerpt — with a link to the underlying note / entity / document
 * page where applicable.
 */

export function ChatCitation({
  index,
  sources,
  workspaceId,
}: {
  index: number;
  sources: CitationSource[];
  workspaceId: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <span className="relative inline-block align-baseline">
      <button
        type="button"
        aria-label={`Citation ${index + 1}`}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className="ml-0.5 cursor-pointer rounded-sm border border-primary/40 bg-primary/10 px-1 align-super text-[10px] font-medium text-foreground transition-colors duration-150 hover:bg-primary/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {index + 1}
      </button>
      {open ? (
        <div
          role="tooltip"
          className="absolute left-0 top-full z-30 mt-1 w-80 rounded-md border border-input bg-popover/90 p-2 text-caption text-muted-foreground shadow-lg backdrop-blur"
        >
          {sources.length === 0 ? (
            <p className="text-muted-foreground">No source detail</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {sources.map((s, i) => (
                <li key={`${s.kind}-${s.id ?? i}`} className="text-muted-foreground">
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground">
                    {s.kind}
                  </p>
                  {s.excerpt ? (
                    <blockquote className="mt-1 border-l-2 border-primary/60 pl-2 text-muted-foreground">
                      {s.excerpt}
                    </blockquote>
                  ) : null}
                  <SourceLink source={s} workspaceId={workspaceId} />
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </span>
  );
}

function SourceLink({
  source,
  workspaceId,
}: {
  source: CitationSource;
  workspaceId: string;
}) {
  const href = sourceHref(source, workspaceId);
  if (!href) return null;
  return (
    <Link
      href={href}
      className="mt-1 inline-block text-foreground hover:underline"
    >
      Open →
    </Link>
  );
}

function sourceHref(source: CitationSource, workspaceId: string): string | null {
  if (!source.id) return null;
  switch (source.kind) {
    case "note":
      return `/notes?note=${encodeURIComponent(source.id)}`;
    case "entity":
      return `/graph?seed_entity_ids=${encodeURIComponent(source.id)}`;
    case "relationship":
      // No dedicated relationship detail page yet — link to the graph.
      return `/graph`;
    case "episode":
      if (source.document_id) {
        const page = source.page_start ?? 1;
        return `/documents/${encodeURIComponent(source.document_id)}?page=${page}`;
      }
      return null;
    case "document":
    case "document_page": {
      if (source.document_id) {
        const page = source.page_start ?? 1;
        return `/documents/${encodeURIComponent(source.document_id)}?page=${page}`;
      }
      return null;
    }
    default:
      return null;
  }
  // (workspaceId reserved for future per-workspace prefixing.)
  void workspaceId;
}
