"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/**
 * Graph filter: PDF documents and North-imported conversation transcripts.
 * Same ``document_id`` query param as before; lists ``source_kind=all`` from the API.
 */

type SourceRow = {
  id: string;
  original_filename: string;
  status: string;
  page_count?: number | null;
  created_at?: string;
  source_kind: string;
  conversation_title?: string | null;
  agent_display_name?: string | null;
};

function rowPrimaryLabel(r: SourceRow): string {
  if (r.source_kind === "north_conversation") {
    const t = (r.conversation_title ?? "").trim();
    return t || r.original_filename;
  }
  return r.original_filename;
}

function rowSecondaryLine(r: SourceRow): string {
  if (r.source_kind === "north_conversation") {
    const agent = (r.agent_display_name ?? "").trim();
    const parts = ["Conversation"];
    if (agent) parts.push(agent);
    parts.push(r.status);
    return parts.join(" · ");
  }
  return [r.status, r.page_count ? `${r.page_count} pp` : ""].filter(Boolean).join(" · ");
}

export function SourcePicker({
  workspaceId,
  value,
  onChange,
}: {
  workspaceId: string;
  value: string;
  onChange: (id: string) => void;
}) {
  const [rows, setRows] = useState<SourceRow[] | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/documents?source_kind=all`,
          { cache: "no-store" },
        );
        const body = (await res.json()) as {
          items?: SourceRow[];
          error?: { message?: string };
        };
        if (cancelled) return;
        const ready = (body.items ?? []).filter(
          (d) => d.status === "ready" || d.status === "building_graph",
        );
        setRows(ready);
      } catch {
        if (!cancelled) setRows([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const selected = useMemo(() => (rows ?? []).find((d) => d.id === value) ?? null, [rows, value]);

  const inputDisplay = open ? query : selected ? rowPrimaryLabel(selected) : query;

  const filtered = useMemo(() => {
    if (!rows) return [];
    const q = query.trim().toLowerCase();
    const match = (r: SourceRow) => {
      if (!q) return true;
      const primary = rowPrimaryLabel(r).toLowerCase();
      const agent = (r.agent_display_name ?? "").toLowerCase();
      const fn = r.original_filename.toLowerCase();
      return primary.includes(q) || agent.includes(q) || fn.includes(q);
    };
    const list = q ? rows.filter(match) : rows;
    return list.slice(0, 60);
  }, [rows, query]);

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
    (d: SourceRow | null) => {
      onChange(d?.id ?? "");
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

  const listboxId = `source-listbox-${workspaceId}`;

  return (
    <div ref={wrapperRef} className="text-caption text-muted">
      <label className="block">
        Sources
        <div className="relative mt-1">
          <input
            type="text"
            value={inputDisplay}
            placeholder={rows === null ? "Loading…" : "Search PDFs and imported conversations…"}
            disabled={rows === null}
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
            className="w-full cursor-pointer rounded border border-border-strong bg-surface px-2 py-1 text-secondary placeholder:text-muted/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary disabled:opacity-50"
          />
          {selected && !open ? (
            <button
              type="button"
              aria-label="Clear source selection"
              onClick={() => choose(null)}
              className="absolute right-1 top-1/2 -translate-y-1/2 cursor-pointer rounded p-0.5 text-muted transition-colors duration-150 hover:bg-surface-raised hover:text-secondary"
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
              className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-border-strong bg-surface-overlay shadow-modal backdrop-blur"
            >
              {filtered.map((d, idx) => (
                <li
                  key={d.id}
                  role="option"
                  aria-selected={idx === activeIdx}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    choose(d);
                  }}
                  onMouseEnter={() => setActiveIdx(idx)}
                  className={`cursor-pointer px-2 py-1.5 text-secondary transition-colors duration-150 ${
                    idx === activeIdx ? "bg-surface-raised" : ""
                  } hover:bg-surface-raised`}
                >
                  <span className="flex items-center gap-1.5">
                    <span
                      className={`shrink-0 rounded px-1 py-0.5 text-[9px] font-medium uppercase tracking-wide ${
                        d.source_kind === "pdf"
                          ? "bg-primary/15 text-primary"
                          : "bg-amber-500/15 text-amber-100"
                      }`}
                    >
                      {d.source_kind === "pdf" ? "PDF" : "Conv"}
                    </span>
                    <span className="block min-w-0 flex-1 truncate">{rowPrimaryLabel(d)}</span>
                  </span>
                  <span className="mt-0.5 block truncate pl-[3.25rem] text-[10px] text-muted">
                    {rowSecondaryLine(d)}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {open && filtered.length === 0 ? (
            <p className="absolute z-20 mt-1 w-full rounded-md border border-border-strong bg-surface-overlay px-2 py-1.5 text-muted">
              No matching sources.
            </p>
          ) : null}
        </div>
      </label>
    </div>
  );
}
