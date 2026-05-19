"use client";

import { AgentPicker } from "@/components/filters/agent-picker";

export type NoteListItem = {
  id: string;
  title: string;
  origin: string;
  updated_at: string;
  tags?: string[];
};

export function NotesList({
  items,
  selectedId,
  onSelect,
  loading,
  error,
  q,
  origin,
  documentFilter,
  agentFilter,
  onQChange,
  onOriginChange,
  onDocumentFilterChange,
  onAgentFilterChange,
  onNewNote,
  workspaceId,
}: {
  items: NoteListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
  error: string | null;
  q: string;
  origin: string;
  documentFilter: string;
  agentFilter: string;
  onQChange: (v: string) => void;
  onOriginChange: (v: string) => void;
  onDocumentFilterChange: (v: string) => void;
  onAgentFilterChange: (v: string) => void;
  onNewNote: () => void;
  workspaceId?: string;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 border-r border-border-subtle pr-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="rounded-md bg-accent-primary px-3 py-1.5 text-caption font-medium text-canvas"
          onClick={onNewNote}
        >
          New note
        </button>
      </div>
      <label className="block text-caption text-muted">
        Search
        <input
          value={q}
          onChange={(e) => onQChange(e.target.value)}
          className="mt-1 w-full rounded-md border border-border-strong bg-surface px-2 py-1 text-body text-secondary"
          placeholder="Title or body…"
        />
      </label>
      <label className="block text-caption text-muted">
        Origin
        <select
          value={origin}
          onChange={(e) => onOriginChange(e.target.value)}
          className="mt-1 w-full rounded-md border border-border-strong bg-surface px-2 py-1 text-body text-secondary"
        >
          <option value="">Any</option>
          <option value="manual">Manual</option>
          <option value="generated">Generated</option>
          <option value="merged">Merged</option>
          <option value="split">Split</option>
        </select>
      </label>
      <label className="block text-caption text-muted">
        Document id filter
        <input
          value={documentFilter}
          onChange={(e) => onDocumentFilterChange(e.target.value)}
          className="mt-1 w-full rounded-md border border-border-strong bg-surface px-2 py-1 font-mono text-caption text-secondary"
          placeholder="Optional uuid"
        />
      </label>
      {workspaceId ? (
        <AgentPicker
          workspaceId={workspaceId}
          value={agentFilter}
          onChange={onAgentFilterChange}
          label="North agent"
          placeholder="All notes (PDF + North)"
        />
      ) : (
        <label className="block text-caption text-muted">
          Agent id filter
          <input
            value={agentFilter}
            onChange={(e) => onAgentFilterChange(e.target.value)}
            className="mt-1 w-full rounded-md border border-border-strong bg-surface px-2 py-1 font-mono text-caption text-secondary"
            placeholder="Optional North agent uuid"
          />
        </label>
      )}

      {error ? (
        <p className="text-caption text-red-300" role="alert">
          {error}
        </p>
      ) : null}

      <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto" aria-label="Notes">
        {loading ? (
          <li className="text-caption text-muted">Loading…</li>
        ) : items.length === 0 ? (
          <li className="text-caption text-muted">No notes match filters.</li>
        ) : (
          items.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                onClick={() => onSelect(n.id)}
                className={`flex w-full flex-col rounded-md border px-2 py-2 text-left transition-colors ${
                  selectedId === n.id
                    ? "border-accent-primary bg-accent-primary/10"
                    : "border-border-subtle bg-surface/40 hover:bg-surface/70"
                }`}
              >
                <span className="text-body font-medium text-secondary">{n.title || "(untitled)"}</span>
                <span className="mt-0.5 flex flex-wrap gap-2 text-caption text-muted">
                  <span className="capitalize">{n.origin}</span>
                  {n.origin === "manual" ? (
                    <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-amber-100">Manual</span>
                  ) : null}
                  <span>{new Date(n.updated_at).toLocaleString()}</span>
                </span>
              </button>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
