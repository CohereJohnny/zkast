"use client";

import { useEffect, useMemo, useState } from "react";

/**
 * Multi-select chip group for entity-type and edge-type filters.
 *
 * Options arrive from ``/api/v1/workspaces/{ws}/graph/types`` so users
 * see only types that *exist* in their workspace (with counts), not a
 * generic list. Selected types serialize back to the same
 * comma-separated query-string format the canvas already consumes,
 * preserving the contract with ``searchParamsToGraphFilters``.
 */

type TypeRow = { name: string; count: number };

export function TypeMultiselect({
  workspaceId,
  kind,
  value,
  onChange,
  label,
}: {
  workspaceId: string;
  /** Determines which key on /graph/types to use. */
  kind: "entity_types" | "edge_types";
  value: string;
  onChange: (csv: string) => void;
  label: string;
}) {
  const [options, setOptions] = useState<TypeRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/graph/types`,
          { cache: "no-store" },
        );
        const body = (await res.json()) as {
          entity_types?: TypeRow[];
          edge_types?: TypeRow[];
          error?: { message?: string };
        };
        if (cancelled) return;
        if (!res.ok) {
          setError(body.error?.message ?? "Failed to load types");
          setOptions([]);
          return;
        }
        setOptions((kind === "entity_types" ? body.entity_types : body.edge_types) ?? []);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to load types");
        setOptions([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId, kind]);

  const selectedSet = useMemo(
    () =>
      new Set(
        value
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      ),
    [value],
  );

  const toggle = (name: string) => {
    const next = new Set(selectedSet);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    onChange(Array.from(next).join(","));
  };

  if (options === null) {
    return (
      <div className="text-caption text-muted-foreground">
        <p>{label}</p>
        <p className="mt-1 text-muted-foreground">Loading…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-caption text-muted-foreground">
        <p>{label}</p>
        <p className="mt-1 text-red-300">{error}</p>
      </div>
    );
  }

  if (options.length === 0) {
    return (
      <div className="text-caption text-muted-foreground">
        <p>{label}</p>
        <p className="mt-1 text-muted-foreground/80">
          No {kind === "entity_types" ? "entity" : "edge"} types yet. Ingest a document to populate.
        </p>
      </div>
    );
  }

  return (
    <fieldset className="text-caption text-muted-foreground">
      <legend className="float-none mb-1 inline-block">{label}</legend>
      <ul className="flex flex-wrap gap-1.5" role="listbox" aria-multiselectable="true">
        {options.map((opt) => {
          const active = selectedSet.has(opt.name);
          return (
            <li key={opt.name}>
              <button
                type="button"
                role="option"
                aria-selected={active}
                onClick={() => toggle(opt.name)}
                className={`flex cursor-pointer items-center gap-1 rounded-full border px-2 py-0.5 text-caption transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  active
                    ? "border-primary bg-primary/15 text-muted-foreground"
                    : "border-input bg-card text-muted-foreground hover:border-input/80 hover:bg-secondary hover:text-muted-foreground"
                }`}
              >
                <span>{opt.name}</span>
                <span className="text-[10px] text-muted-foreground">{opt.count}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}
