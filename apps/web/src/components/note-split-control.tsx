"use client";

export function NoteSplitControl({
  selection,
  busy,
  onSplit,
}: {
  selection: string | null;
  busy?: boolean;
  onSplit: () => void;
}) {
  if (!selection?.trim()) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-border-subtle bg-surface/40 px-3 py-2">
      <span className="text-caption text-muted">
        Selected {selection.length} characters — splits verbatim text into a new linked note.
      </span>
      <button
        type="button"
        disabled={busy}
        className="rounded-md bg-accent-primary px-2 py-1 text-caption font-medium text-canvas disabled:opacity-50"
        onClick={onSplit}
      >
        Split selection
      </button>
    </div>
  );
}
