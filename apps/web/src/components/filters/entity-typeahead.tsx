"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/**
 * Multi-select typeahead for the "seed entity IDs" filter.
 *
 * Type → debounced fetch to ``/graph/entities/search-typeahead?q=`` →
 * dropdown of candidate entities (name + type + degree) → click adds a
 * chip. Selected chips display name + small type badge; the underlying
 * value remains a comma-separated UUID list to preserve the existing
 * ``seed_entity_ids`` query-string contract.
 */

type EntityHit = {
  id: string;
  name: string;
  type: string;
  degree: number;
};

const DEBOUNCE_MS = 220;

export function EntityTypeahead({
  workspaceId,
  value,
  onChange,
  label = "Seed entities (subgraph)",
  placeholder = "Search entities by name…",
}: {
  workspaceId: string;
  /** Comma-separated UUID list (matches existing seed_entity_ids contract). */
  value: string;
  onChange: (csv: string) => void;
  label?: string;
  placeholder?: string;
}) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<EntityHit[]>([]);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  // Cache of id → metadata so chips can render name + type after page
  // reload (when only the UUID is in the URL).
  const [knownById, setKnownById] = useState<Record<string, EntityHit>>({});
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  const selectedIds = useMemo(
    () =>
      value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    [value],
  );

  // When deep-linked, we don't have the name/type for already-selected
  // entities yet. Fire one bulk lookup so the chips render properly.
  useEffect(() => {
    const missing = selectedIds.filter((id) => !knownById[id]);
    if (missing.length === 0) return;
    let cancelled = false;
    void (async () => {
      // The typeahead endpoint searches by name, not id. The cheapest
      // path: hit the existing entity-detail endpoint per missing id
      // (small N: usually 0–3). For 1–3 it's well under a second.
      const lookups = await Promise.all(
        missing.map(async (id) => {
          try {
            const res = await fetch(
              `/api/v1/workspaces/${workspaceId}/graph/entities/${id}?neighbor_depth=0&neighbor_limit=1`,
              { cache: "no-store" },
            );
            const body = (await res.json()) as {
              entity?: { id: string; name: string; type: string };
            };
            if (body.entity) {
              return {
                id: body.entity.id,
                name: body.entity.name,
                type: body.entity.type,
                degree: 0,
              } as EntityHit;
            }
          } catch {
            /* swallow — chip will render the bare uuid */
          }
          return null;
        }),
      );
      if (cancelled) return;
      const next: Record<string, EntityHit> = {};
      for (const e of lookups) {
        if (e) next[e.id] = e;
      }
      if (Object.keys(next).length > 0) {
        setKnownById((prev) => ({ ...prev, ...next }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, selectedIds, knownById]);

  // Debounced search.
  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setHits([]);
      return;
    }
    let cancelled = false;
    setBusy(true);
    const t = window.setTimeout(async () => {
      try {
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/graph/entities/search-typeahead?q=${encodeURIComponent(q)}&limit=20`,
          { cache: "no-store" },
        );
        const body = (await res.json()) as { items?: EntityHit[] };
        if (cancelled) return;
        const items = body.items ?? [];
        setHits(items);
        setActiveIdx(0);
        // Add discovered entities to the metadata cache so future chips render.
        if (items.length > 0) {
          setKnownById((prev) => {
            const next = { ...prev };
            for (const i of items) next[i.id] = i;
            return next;
          });
        }
      } catch {
        if (!cancelled) setHits([]);
      } finally {
        if (!cancelled) setBusy(false);
      }
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [workspaceId, query]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const addChip = useCallback(
    (hit: EntityHit) => {
      if (selectedIds.includes(hit.id)) {
        setQuery("");
        setOpen(false);
        return;
      }
      const next = [...selectedIds, hit.id];
      onChange(next.join(","));
      setQuery("");
      setOpen(false);
    },
    [selectedIds, onChange],
  );

  const removeChip = useCallback(
    (id: string) => {
      onChange(selectedIds.filter((x) => x !== id).join(","));
    },
    [selectedIds, onChange],
  );

  const listboxId = `entity-typeahead-${workspaceId}`;

  return (
    <div ref={wrapperRef} className="text-caption text-muted-foreground">
      <label className="block">
        {label}
        {selectedIds.length > 0 ? (
          <ul
            className="mt-1 mb-1 flex flex-wrap gap-1"
            aria-label="Selected entities"
          >
            {selectedIds.map((id) => {
              const meta = knownById[id];
              return (
                <li
                  key={id}
                  className="flex items-center gap-1 rounded-full border border-input bg-secondary px-2 py-0.5 text-muted-foreground"
                >
                  <span className="truncate max-w-[12rem]">
                    {meta ? meta.name : id.slice(0, 8)}
                  </span>
                  {meta?.type ? (
                    <span className="text-[10px] text-muted-foreground">· {meta.type}</span>
                  ) : null}
                  <button
                    type="button"
                    aria-label={`Remove ${meta?.name ?? id}`}
                    onClick={() => removeChip(id)}
                    className="cursor-pointer rounded p-0.5 text-muted-foreground hover:bg-card hover:text-muted-foreground"
                  >
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 24 24"
                      className="h-3 w-3"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M18 6 6 18M6 6l12 12" />
                    </svg>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : null}
        <div className="relative">
          <input
            type="text"
            value={query}
            placeholder={placeholder}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setOpen(true);
                setActiveIdx((i) => Math.min(i + 1, hits.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActiveIdx((i) => Math.max(i - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                if (open && hits[activeIdx]) addChip(hits[activeIdx]);
              } else if (e.key === "Escape") {
                setOpen(false);
              } else if (
                e.key === "Backspace" &&
                query === "" &&
                selectedIds.length > 0
              ) {
                removeChip(selectedIds[selectedIds.length - 1]);
              }
            }}
            role="combobox"
            aria-controls={listboxId}
            aria-expanded={open}
            aria-autocomplete="list"
            className="w-full cursor-text rounded border border-input bg-card px-2 py-1 text-muted-foreground placeholder:text-muted-foreground/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          {open && (busy || hits.length > 0 || query.trim()) ? (
            <ul
              role="listbox"
              id={listboxId}
              className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-input bg-popover/90 shadow-lg backdrop-blur"
            >
              {busy ? (
                <li className="px-2 py-1.5 text-muted-foreground">Searching…</li>
              ) : hits.length === 0 ? (
                <li className="px-2 py-1.5 text-muted-foreground">No matches.</li>
              ) : (
                hits.map((h, idx) => (
                  <li
                    key={h.id}
                    role="option"
                    aria-selected={idx === activeIdx}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      addChip(h);
                    }}
                    onMouseEnter={() => setActiveIdx(idx)}
                    className={`flex cursor-pointer items-center justify-between px-2 py-1.5 text-muted-foreground ${
                      idx === activeIdx ? "bg-secondary" : ""
                    } hover:bg-secondary`}
                  >
                    <span className="block flex-1 truncate">
                      <span>{h.name}</span>
                      <span className="ml-2 text-[10px] text-muted-foreground">{h.type}</span>
                    </span>
                    <span className="ml-2 text-[10px] text-muted-foreground">
                      deg {h.degree}
                    </span>
                  </li>
                ))
              )}
            </ul>
          ) : null}
        </div>
      </label>
    </div>
  );
}
