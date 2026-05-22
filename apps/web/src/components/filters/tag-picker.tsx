"use client";

import { useEffect, useMemo, useRef, useState } from "react";

/**
 * Single-select combobox over distinct atomic-note tags.
 *
 * Smaller and simpler than DocumentPicker because tag values are short
 * and the option count is usually under 50. We still render a typeahead
 * filter so a large vocabulary stays manageable.
 */

type TagRow = { name: string; count: number };

export function TagPicker({
  workspaceId,
  value,
  onChange,
  label = "Tag",
  placeholder = "Note tag…",
}: {
  workspaceId: string;
  value: string;
  onChange: (tag: string) => void;
  label?: string;
  placeholder?: string;
}) {
  const [tags, setTags] = useState<TagRow[] | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/notes/tags`,
          { cache: "no-store" },
        );
        const body = (await res.json()) as { tags?: TagRow[] };
        if (cancelled) return;
        setTags(body.tags ?? []);
      } catch {
        if (!cancelled) setTags([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

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

  const filtered = useMemo(() => {
    if (!tags) return [];
    const q = query.trim().toLowerCase();
    if (!q) return tags.slice(0, 50);
    return tags.filter((t) => t.name.toLowerCase().includes(q)).slice(0, 50);
  }, [tags, query]);

  const listboxId = `tag-listbox-${workspaceId}`;

  const inputDisplay = open ? query : value || query;

  return (
    <div ref={wrapperRef} className="text-caption text-muted-foreground">
      <label className="block">
        {label}
        <div className="relative mt-1">
          <input
            type="text"
            value={inputDisplay}
            placeholder={tags === null ? "Loading…" : placeholder}
            disabled={tags === null}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
              setActiveIdx(0);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setOpen(true);
                setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActiveIdx((i) => Math.max(i - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                if (open && filtered[activeIdx]) {
                  onChange(filtered[activeIdx].name);
                  setOpen(false);
                  setQuery("");
                } else if (query.trim()) {
                  // Allow free-text tags that aren't in the existing
                  // vocabulary yet — useful when the user is filtering
                  // before the first ingestion completes.
                  onChange(query.trim());
                  setOpen(false);
                  setQuery("");
                }
              } else if (e.key === "Escape") {
                setOpen(false);
                setQuery("");
              }
            }}
            role="combobox"
            aria-controls={listboxId}
            aria-expanded={open}
            aria-autocomplete="list"
            className="w-full cursor-pointer rounded border border-input bg-card px-2 py-1 text-muted-foreground placeholder:text-muted-foreground/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          />
          {value && !open ? (
            <button
              type="button"
              aria-label="Clear tag selection"
              onClick={() => {
                onChange("");
                setQuery("");
              }}
              className="absolute right-1 top-1/2 -translate-y-1/2 cursor-pointer rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-muted-foreground"
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
              {filtered.map((t, idx) => (
                <li
                  key={t.name}
                  role="option"
                  aria-selected={idx === activeIdx}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    onChange(t.name);
                    setOpen(false);
                    setQuery("");
                  }}
                  onMouseEnter={() => setActiveIdx(idx)}
                  className={`flex cursor-pointer items-center justify-between px-2 py-1.5 text-muted-foreground ${
                    idx === activeIdx ? "bg-secondary" : ""
                  } hover:bg-secondary`}
                >
                  <span className="truncate">{t.name}</span>
                  <span className="ml-2 text-[10px] text-muted-foreground">{t.count}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </label>
    </div>
  );
}
