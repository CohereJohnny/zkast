"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/**
 * Unified source/scope filter used by Notes and Graph.
 *
 * One combobox that lists:
 *  - Memory spaces: agents and Slack channels (scope by agent_id — everything
 *    in that space)
 *  - Documents: PDFs, agent conversations, and Slack sessions/threads (scope by
 *    document_id — just that source)
 *
 * Emits a discriminated selection so callers map to the right query param.
 */

export type SourceScopeSelection = { kind: "agent" | "document"; id: string };

type AgentRow = {
  id: string;
  display_name?: string | null;
  external_agent_id?: string | null;
  provider?: string | null;
};

type DocRow = {
  id: string;
  original_filename: string;
  status: string;
  source_kind: string;
  conversation_title?: string | null;
  agent_display_name?: string | null;
};

type OptionGroup = "channels" | "agents" | "documents";

type Option = {
  kind: "agent" | "document";
  id: string;
  primary: string;
  secondary: string;
  group: OptionGroup;
  badge: string;
  badgeClass: string;
};

const GROUP_LABEL: Record<OptionGroup, string> = {
  channels: "Slack channels (whole memory space)",
  agents: "Agents (whole memory space)",
  documents: "Documents (single source)",
};

function docPrimary(d: DocRow): string {
  if (d.source_kind === "north_conversation" || d.source_kind === "slack_conversation") {
    return (d.conversation_title ?? "").trim() || d.original_filename;
  }
  return d.original_filename;
}

function buildOptions(agents: AgentRow[], docs: DocRow[]): Option[] {
  const out: Option[] = [];
  for (const a of agents) {
    const isSlack = a.provider === "slack";
    const name = (a.display_name ?? "").trim() || a.external_agent_id || a.id;
    out.push({
      kind: "agent",
      id: a.id,
      primary: isSlack ? `#${name}` : name,
      secondary: isSlack ? "All notes & graph in this channel" : "All notes & graph for this agent",
      group: isSlack ? "channels" : "agents",
      badge: isSlack ? "Channel" : "Agent",
      badgeClass: isSlack ? "bg-fuchsia-500/15 text-fuchsia-200" : "bg-primary/15 text-foreground",
    });
  }
  for (const d of docs) {
    const isSlack = d.source_kind === "slack_conversation";
    const isConv = d.source_kind === "north_conversation";
    out.push({
      kind: "document",
      id: d.id,
      primary: docPrimary(d),
      secondary: isSlack
        ? `Slack${d.agent_display_name ? ` · #${d.agent_display_name}` : ""} · ${d.status}`
        : isConv
          ? `Conversation${d.agent_display_name ? ` · ${d.agent_display_name}` : ""} · ${d.status}`
          : `PDF · ${d.status}`,
      group: "documents",
      badge: d.source_kind === "pdf" ? "PDF" : isSlack ? "Session" : "Conv",
      badgeClass:
        d.source_kind === "pdf"
          ? "bg-primary/15 text-foreground"
          : isSlack
            ? "bg-fuchsia-500/10 text-fuchsia-200/90"
            : "bg-amber-500/15 text-amber-100",
    });
  }
  return out;
}

export function SourceScopeFilter({
  workspaceId,
  value,
  onChange,
  label = "Sources",
}: {
  workspaceId: string;
  value: SourceScopeSelection | null;
  onChange: (next: SourceScopeSelection | null) => void;
  label?: string;
}) {
  const [options, setOptions] = useState<Option[] | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [aRes, dRes] = await Promise.all([
          fetch(`/api/v1/workspaces/${workspaceId}/north/agents`, { cache: "no-store" }),
          fetch(`/api/v1/workspaces/${workspaceId}/documents?source_kind=all`, { cache: "no-store" }),
        ]);
        const aBody = (await aRes.json().catch(() => ({}))) as { items?: AgentRow[] };
        const dBody = (await dRes.json().catch(() => ({}))) as { items?: DocRow[] };
        if (cancelled) return;
        const docs = (dBody.items ?? []).filter(
          (d) => d.status === "ready" || d.status === "building_graph",
        );
        setOptions(buildOptions(aBody.items ?? [], docs));
      } catch {
        if (!cancelled) setOptions([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const selected = useMemo(
    () => (options ?? []).find((o) => o.kind === value?.kind && o.id === value?.id) ?? null,
    [options, value],
  );

  const inputDisplay = open ? query : selected ? selected.primary : query;

  const filtered = useMemo(() => {
    if (!options) return [];
    const q = query.trim().toLowerCase();
    const match = (o: Option) =>
      !q || o.primary.toLowerCase().includes(q) || o.secondary.toLowerCase().includes(q);
    const list = q ? options.filter(match) : options;
    // Channels first (always visible), then agents, then documents — caps keep
    // big workspaces responsive while guaranteeing memory spaces show.
    const channels = list.filter((o) => o.group === "channels").slice(0, 40);
    const agents = list.filter((o) => o.group === "agents").slice(0, 40);
    const docs = list.filter((o) => o.group === "documents").slice(0, 60);
    return [...channels, ...agents, ...docs];
  }, [options, query]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    }
    if (open) document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const choose = useCallback(
    (o: Option | null) => {
      onChange(o ? { kind: o.kind, id: o.id } : null);
      setOpen(false);
      setQuery("");
    },
    [onChange],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (open && filtered[activeIdx]) choose(filtered[activeIdx]);
    } else if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
    }
  };

  const listboxId = `source-scope-listbox-${workspaceId}`;
  let renderedGroup: OptionGroup | null = null;

  return (
    <div ref={wrapperRef} className="text-caption text-muted-foreground">
      <label className="block">
        {label}
        <div className="relative mt-1">
          <input
            type="text"
            value={inputDisplay}
            placeholder={options === null ? "Loading…" : "Filter by agent, Slack channel, or document…"}
            disabled={options === null}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
              setActiveIdx(0);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
            role="combobox"
            aria-controls={listboxId}
            aria-expanded={open}
            aria-autocomplete="list"
            className="w-full cursor-pointer rounded border border-input bg-card px-2 py-1 text-muted-foreground placeholder:text-muted-foreground/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          />
          {selected && !open ? (
            <button
              type="button"
              aria-label="Clear source selection"
              onClick={() => choose(null)}
              className="absolute right-1 top-1/2 -translate-y-1/2 cursor-pointer rounded p-0.5 text-muted-foreground hover:bg-secondary"
            >
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                className="h-3.5 w-3.5"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          ) : null}
          {open && filtered.length > 0 ? (
            <ul
              role="listbox"
              id={listboxId}
              className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-md border border-input bg-popover/95 shadow-lg backdrop-blur"
            >
              {filtered.map((o, idx) => {
                const showHeader = o.group !== renderedGroup;
                renderedGroup = o.group;
                return (
                  <li key={`${o.kind}:${o.id}`}>
                    {showHeader ? (
                      <p className="px-2 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                        {GROUP_LABEL[o.group]}
                      </p>
                    ) : null}
                    <button
                      type="button"
                      role="option"
                      aria-selected={idx === activeIdx}
                      onMouseDown={(e) => {
                        e.preventDefault();
                        choose(o);
                      }}
                      onMouseEnter={() => setActiveIdx(idx)}
                      className={`block w-full cursor-pointer px-2 py-1.5 text-left text-muted-foreground hover:bg-secondary ${
                        idx === activeIdx ? "bg-secondary" : ""
                      }`}
                    >
                      <span className="flex items-center gap-1.5">
                        <span
                          className={`shrink-0 rounded px-1 py-0.5 text-[9px] font-medium uppercase tracking-wide ${o.badgeClass}`}
                        >
                          {o.badge}
                        </span>
                        <span className="block min-w-0 flex-1 truncate">{o.primary}</span>
                      </span>
                      <span className="mt-0.5 block truncate pl-[3.25rem] text-[10px] text-muted-foreground">
                        {o.secondary}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {open && filtered.length === 0 ? (
            <p className="absolute z-20 mt-1 w-full rounded-md border border-input bg-popover/95 px-2 py-1.5 text-muted-foreground">
              No matching sources.
            </p>
          ) : null}
        </div>
      </label>
    </div>
  );
}
