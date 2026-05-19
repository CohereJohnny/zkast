"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type NorthAgent = {
  id: string;
  display_name: string;
  external_agent_id: string;
};

export function AgentPicker({
  workspaceId,
  value,
  onChange,
  label = "North agent",
  placeholder = "All agents (workspace)",
  allowClear = true,
}: {
  workspaceId: string;
  value: string;
  onChange: (id: string) => void;
  label?: string;
  placeholder?: string;
  allowClear?: boolean;
}) {
  const [agents, setAgents] = useState<NorthAgent[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(`/api/v1/workspaces/${workspaceId}/north/agents`, {
          cache: "no-store",
        });
        const body = (await res.json()) as { items?: NorthAgent[]; error?: { message?: string } };
        if (cancelled) return;
        if (!res.ok) {
          setLoadError(body.error?.message ?? `HTTP ${res.status}`);
          setAgents([]);
          return;
        }
        setLoadError(null);
        setAgents(body.items ?? []);
      } catch {
        if (!cancelled) {
          setLoadError("Failed to load agents");
          setAgents([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const selected = useMemo(
    () => (agents ?? []).find((a) => a.id === value) ?? null,
    [agents, value],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = agents ?? [];
    if (!q) return list;
    return list.filter(
      (a) =>
        a.display_name.toLowerCase().includes(q) ||
        a.external_agent_id.toLowerCase().includes(q) ||
        a.id.toLowerCase().includes(q),
    );
  }, [agents, query]);

  useEffect(() => {
    setActiveIdx(0);
  }, [filtered.length, query]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const pick = useCallback(
    (id: string) => {
      onChange(id);
      setQuery("");
      setOpen(false);
    },
    [onChange],
  );

  const displayValue = open
    ? query
    : selected
      ? selected.display_name || selected.external_agent_id
      : value
        ? `${value.slice(0, 8)}…`
        : "";

  return (
    <label className="relative block text-caption text-muted">
      {label}
      <div ref={wrapperRef} className="relative mt-1">
        <input
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          placeholder={placeholder}
          value={displayValue}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
            if (!e.target.value.trim() && allowClear) onChange("");
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActiveIdx((i) => Math.min(i + 1, Math.max(0, filtered.length - 1)));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActiveIdx((i) => Math.max(i - 1, 0));
            } else if (e.key === "Enter" && open && filtered[activeIdx]) {
              e.preventDefault();
              pick(filtered[activeIdx].id);
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          className="w-full rounded-md border border-border-strong bg-surface px-2 py-1 text-body text-secondary"
        />
        {allowClear && value ? (
          <button
            type="button"
            className="absolute right-1 top-1/2 -translate-y-1/2 rounded px-1 text-caption text-muted hover:text-secondary"
            onClick={() => pick("")}
            aria-label="Clear agent filter"
          >
            ×
          </button>
        ) : null}
        {open && filtered.length > 0 ? (
          <ul
            role="listbox"
            className="absolute z-20 mt-1 max-h-48 w-full overflow-auto rounded-md border border-border-strong bg-surface py-1 shadow-lg"
          >
            {filtered.map((a, idx) => (
              <li key={a.id} role="option" aria-selected={idx === activeIdx}>
                <button
                  type="button"
                  className={`flex w-full flex-col px-2 py-1.5 text-left text-body ${
                    idx === activeIdx
                      ? "bg-accent-primary/15 text-primary"
                      : "text-secondary hover:bg-surface-raised"
                  }`}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    pick(a.id);
                  }}
                >
                  <span className="truncate">{a.display_name || a.external_agent_id}</span>
                  <span className="truncate font-mono text-[10px] text-muted">
                    {a.external_agent_id}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {open && agents && filtered.length === 0 ? (
          <p className="absolute z-20 mt-1 w-full rounded-md border border-border-subtle bg-surface px-2 py-2 text-caption text-muted">
            {loadError ?? "No matching agents"}
          </p>
        ) : null}
      </div>
    </label>
  );
}
