"use client";

import { useEffect, useState } from "react";

import {
  SourceScopeFilter,
  type SourceScopeSelection,
} from "@/components/filters/source-scope-filter";
import { EntityTypeahead } from "@/components/filters/entity-typeahead";
import { TagPicker } from "@/components/filters/tag-picker";
import { TypeMultiselect } from "@/components/filters/type-multiselect";

/**
 * Sprint 6 — session scope picker used at session-create time.
 *
 * Reuses every Sprint 5c filter component plus a snapshot combobox and a
 * date input for ``valid_at``. The emitted ``scope`` object matches
 * ``ChatSession.scope`` in [`specs/datamodel.md`](../../../specs/datamodel.md).
 *
 * All inputs are optional — leaving the form empty creates a session
 * scoped to the whole workspace.
 */

export type ChatScopeValue = {
  document_ids?: string[];
  tags?: string[];
  entity_types?: string[];
  edge_types?: string[];
  seed_entity_ids?: string[];
  valid_at?: string;
  pinned_snapshot_id?: string | null;
  /** When set, graph + hybrid retrieval restrict to documents owned by this North agent. */
  agent_id?: string;
};

type SnapshotRow = {
  id: string;
  name: string;
  created_at?: string;
};

export function ChatScopePicker({
  workspaceId,
  value,
  onChange,
}: {
  workspaceId: string;
  value: ChatScopeValue;
  onChange: (next: ChatScopeValue) => void;
}) {
  const [snapshots, setSnapshots] = useState<SnapshotRow[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/snapshots`,
          { cache: "no-store" },
        );
        const body = (await res.json()) as { items?: SnapshotRow[] };
        if (cancelled) return;
        setSnapshots(body.items ?? []);
      } catch {
        if (!cancelled) setSnapshots([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  const patch = (delta: Partial<ChatScopeValue>) => {
    onChange({ ...value, ...delta });
  };

  // The picker components emit CSV; ChatScopeValue keeps arrays so
  // ChatScopePicker is responsible for the marshalling at the seam.
  const toCsv = (arr: string[] | undefined): string =>
    (arr ?? []).join(",");

  const fromCsv = (csv: string): string[] =>
    csv
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

  const sourceSelection: SourceScopeSelection | null = value.agent_id
    ? { kind: "agent", id: value.agent_id }
    : value.document_ids && value.document_ids[0]
      ? { kind: "document", id: value.document_ids[0] }
      : null;

  const onSourceChange = (next: SourceScopeSelection | null) => {
    if (!next) {
      patch({ agent_id: undefined, document_ids: [] });
    } else if (next.kind === "agent") {
      patch({ agent_id: next.id, document_ids: [] });
    } else {
      patch({ agent_id: undefined, document_ids: [next.id] });
    }
  };

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <SourceScopeFilter
          workspaceId={workspaceId}
          value={sourceSelection}
          onChange={onSourceChange}
          label="Grounding scope (optional)"
        />
        <p className="mt-1 text-caption text-muted-foreground">
          Restrict grounding to one memory space (agent or Slack channel — all its documents and
          notes) or a single document. Leave empty for workspace-wide retrieval.
        </p>
      </div>
      <EntityTypeahead
        workspaceId={workspaceId}
        value={toCsv(value.seed_entity_ids)}
        onChange={(csv) => patch({ seed_entity_ids: fromCsv(csv) })}
        label="Seed entities (optional)"
      />
      <TagPicker
        workspaceId={workspaceId}
        value={(value.tags ?? [])[0] ?? ""}
        onChange={(tag) => patch({ tags: tag ? [tag] : [] })}
        label="Restrict to tag"
      />
      <label className="text-caption text-muted-foreground">
        As-of timestamp (optional)
        <input
          type="datetime-local"
          className="mt-1 w-full rounded border border-input bg-card px-2 py-1 text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          value={value.valid_at ?? ""}
          onChange={(e) =>
            patch({ valid_at: e.target.value || undefined })
          }
        />
      </label>
      <TypeMultiselect
        workspaceId={workspaceId}
        kind="entity_types"
        value={toCsv(value.entity_types)}
        onChange={(csv) => patch({ entity_types: fromCsv(csv) })}
        label="Entity types"
      />
      <TypeMultiselect
        workspaceId={workspaceId}
        kind="edge_types"
        value={toCsv(value.edge_types)}
        onChange={(csv) => patch({ edge_types: fromCsv(csv) })}
        label="Edge types"
      />
      <label className="text-caption text-muted-foreground sm:col-span-2">
        Pin to snapshot (optional)
        <select
          className="mt-1 w-full cursor-pointer rounded border border-input bg-card px-2 py-1 text-muted-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          value={value.pinned_snapshot_id ?? ""}
          onChange={(e) =>
            patch({
              pinned_snapshot_id: e.target.value || null,
            })
          }
        >
          <option value="">No snapshot pin (use live working graph)</option>
          {(snapshots ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
