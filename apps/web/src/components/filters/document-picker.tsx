"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/**
 * Single-select combobox over the workspace's *ready* documents.
 *
 * Replaces the free-form UUID text input previously used in the graph
 * filter bar. The user shouldn't have to know or copy a document's
 * UUID — they should pick by filename.
 *
 * Loads ``/api/v1/workspaces/{ws}/documents?source_kind=pdf`` once on mount, filters
 * client-side on the typed query. Emits ``onChange(id | "")``.
 */

type DocumentRow = {
  id: string;
  original_filename: string;
  status: string;
  page_count?: number;
  created_at?: string;
};

export function DocumentPicker({
  workspaceId,
  value,
  onChange,
  label = "Document",
  placeholder = "Search documents…",
}: {
  workspaceId: string;
  value: string;
  onChange: (id: string) => void;
  label?: string;
  placeholder?: string;
}) {
  const [docs, setDocs] = useState<DocumentRow[] | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/documents?source_kind=pdf`,
          { cache: "no-store" },
        );
        const body = (await res.json()) as {
          items?: DocumentRow[];
          error?: { message?: string };
        };
        if (cancelled) return;
        // Only "ready" documents are interesting as filter values; partial
        // ingests don't have entities to filter by yet.
        const ready = (body.items ?? []).filter(
          (d) => d.status === "ready" || d.status === "building_graph",
        );
        setDocs(ready);
      } catch {
        if (!cancelled) setDocs([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  // Reflect parent-driven changes (e.g. URL deep-link) in the displayed
  // selection.
  const selected = useMemo(
    () => (docs ?? []).find((d) => d.id === value) ?? null,
    [docs, value],
  );

  const inputDisplay = open
    ? query
    : selected
      ? selected.original_filename
      : query;

  const filtered = useMemo(() => {
    if (!docs) return [];
    const q = query.trim().toLowerCase();
    if (!q) return docs.slice(0, 50);
    return docs
      .filter((d) => d.original_filename.toLowerCase().includes(q))
      .slice(0, 50);
  }, [docs, query]);

  // Close on outside click.
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
    (d: DocumentRow | null) => {
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

  const listboxId = `doc-listbox-${workspaceId}`;

  return (
    <div ref={wrapperRef} className="text-caption text-muted-foreground">
      <label className="block">
        {label}
        <div className="relative mt-1">
          <input
            type="text"
            value={inputDisplay}
            placeholder={docs === null ? "Loading…" : placeholder}
            disabled={docs === null}
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
              aria-label="Clear document selection"
              onClick={() => choose(null)}
              className="absolute right-1 top-1/2 -translate-y-1/2 cursor-pointer rounded p-0.5 text-muted-foreground transition-colors duration-150 hover:bg-secondary hover:text-muted-foreground"
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
              className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-input bg-popover/90 shadow-lg backdrop-blur"
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
                  className={`cursor-pointer px-2 py-1.5 text-muted-foreground transition-colors duration-150 ${
                    idx === activeIdx ? "bg-secondary" : ""
                  } hover:bg-secondary`}
                >
                  <span className="block truncate">{d.original_filename}</span>
                  <span className="block text-[10px] text-muted-foreground">
                    {d.status}
                    {d.page_count ? ` · ${d.page_count} pp` : ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {open && filtered.length === 0 ? (
            <p className="absolute z-20 mt-1 w-full rounded-md border border-input bg-popover/90 px-2 py-1.5 text-muted-foreground">
              No matching documents.
            </p>
          ) : null}
        </div>
      </label>
    </div>
  );
}
