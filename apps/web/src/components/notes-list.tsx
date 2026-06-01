"use client";

import {
  NotesSourceFilter,
  type NoteSourceSelection,
} from "@/components/filters/notes-source-filter";

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
  source,
  onQChange,
  onOriginChange,
  onSourceChange,
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
  source: NoteSourceSelection | null;
  onQChange: (v: string) => void;
  onOriginChange: (v: string) => void;
  onSourceChange: (next: NoteSourceSelection | null) => void;
  onNewNote: () => void;
  workspaceId?: string;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-3 border-r border-border pr-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="rounded-md bg-primary px-3 py-1.5 text-caption font-medium text-primary-foreground"
          onClick={onNewNote}
        >
          New note
        </button>
      </div>
      <label className="block text-caption text-muted-foreground">
        Search
        <input
          value={q}
          onChange={(e) => onQChange(e.target.value)}
          className="mt-1 w-full rounded-md border border-input bg-card px-2 py-1 text-p text-muted-foreground"
          placeholder="Title or body…"
        />
      </label>
      <label className="block text-caption text-muted-foreground">
        Origin
        <select
          value={origin}
          onChange={(e) => onOriginChange(e.target.value)}
          className="mt-1 w-full rounded-md border border-input bg-card px-2 py-1 text-p text-muted-foreground"
        >
          <option value="">Any</option>
          <option value="manual">Manual</option>
          <option value="generated">Generated</option>
          <option value="merged">Merged</option>
          <option value="split">Split</option>
        </select>
      </label>
      {workspaceId ? (
        <NotesSourceFilter
          workspaceId={workspaceId}
          value={source}
          onChange={onSourceChange}
        />
      ) : null}

      {error ? (
        <p className="text-caption text-red-300" role="alert">
          {error}
        </p>
      ) : null}

      <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto" aria-label="Notes">
        {loading ? (
          <li className="text-caption text-muted-foreground">Loading…</li>
        ) : items.length === 0 ? (
          <li className="text-caption text-muted-foreground">No notes match filters.</li>
        ) : (
          items.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                onClick={() => onSelect(n.id)}
                className={`flex w-full flex-col rounded-md border px-2 py-2 text-left transition-colors ${
                  selectedId === n.id
                    ? "border-primary bg-primary/10"
                    : "border-border bg-card/40 hover:bg-card/70"
                }`}
              >
                <span className="text-p font-medium text-muted-foreground">{n.title || "(untitled)"}</span>
                <span className="mt-0.5 flex flex-wrap gap-2 text-caption text-muted-foreground">
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
