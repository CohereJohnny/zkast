"use client";

import { useEffect, useMemo, useState } from "react";

import { cn } from "@/lib/utils";

export type OntologyChoice = {
  name: string;
  version: string;
};

type PromptSetSummary = {
  name: string;
  version: string;
  is_builtin?: boolean;
  origin?: string | null;
};

const DEFAULT_ONTOLOGY: OntologyChoice = { name: "generic", version: "v1" };

function choiceKey(c: OntologyChoice): string {
  return `${c.name}|||${c.version}`;
}

function parseChoiceKey(key: string): OntologyChoice | null {
  const idx = key.lastIndexOf("|||");
  if (idx <= 0) return null;
  const name = key.slice(0, idx);
  const version = key.slice(idx + 3);
  if (!name || !version) return null;
  return { name, version };
}

export function OntologyPicker({
  workspaceId,
  value,
  onChange,
  label = "Ontology",
  className,
  compact = false,
}: {
  workspaceId: string;
  value: OntologyChoice;
  onChange: (next: OntologyChoice) => void;
  label?: string;
  className?: string;
  compact?: boolean;
}) {
  const [items, setItems] = useState<PromptSetSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(
          `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/prompt-sets`,
          { cache: "no-store" },
        );
        const body = (await res.json().catch(() => ({}))) as {
          items?: PromptSetSummary[];
          error?: { message?: string };
        };
        if (cancelled) return;
        if (!res.ok) {
          setLoadError(body.error?.message ?? `Failed to load ontologies (${res.status})`);
          setItems([]);
          return;
        }
        setItems(body.items ?? []);
        setLoadError(null);
      } catch {
        if (!cancelled) {
          setLoadError("Failed to load ontologies");
          setItems([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const options = useMemo(() => {
    const list = items ?? [];
    const seen = new Set(list.map((i) => choiceKey(i)));
    const out = [...list];
    if (!seen.has(choiceKey(value))) {
      out.unshift({ name: value.name, version: value.version, is_builtin: false });
    }
    return out;
  }, [items, value]);

  return (
    <label className={cn("block text-caption text-muted-foreground", className)}>
      {label}
      <select
        className={cn(
          "mt-1 w-full cursor-pointer rounded border border-input bg-card px-2 py-1 text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
          compact && "py-0.5 text-caption",
        )}
        value={choiceKey(value)}
        disabled={items === null}
        onChange={(e) => {
          const next = parseChoiceKey(e.target.value);
          if (next) onChange(next);
        }}
        aria-label={label}
      >
        {items === null ? (
          <option value={choiceKey(value)}>Loading…</option>
        ) : (
          options.map((o) => (
            <option key={choiceKey(o)} value={choiceKey(o)}>
              {o.name}/{o.version}
              {o.is_builtin ? " (built-in)" : ""}
            </option>
          ))
        )}
      </select>
      {loadError ? <p className="mt-1 text-[10px] text-destructive">{loadError}</p> : null}
    </label>
  );
}

export { DEFAULT_ONTOLOGY };
