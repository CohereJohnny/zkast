"use client";

import { useState } from "react";

export function NoteMergeDialog({
  open,
  workspaceId,
  survivorNoteId,
  onClose,
  onMerged,
}: {
  open: boolean;
  workspaceId: string;
  survivorNoteId: string;
  onClose: () => void;
  onMerged: (survivorId: string) => void;
}) {
  const [otherId, setOtherId] = useState("");
  const [titlePick, setTitlePick] = useState<"survivor" | "other">("survivor");
  const [bodyPick, setBodyPick] = useState<"survivor" | "other">("survivor");
  const [tagsPick, setTagsPick] = useState<"survivor" | "other">("survivor");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!open) return null;

  const submit = async () => {
    setErr(null);
    setBusy(true);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/notes/${survivorNoteId}/merge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          other_note_id: otherId.trim(),
          field_selection: { title: titlePick, body: bodyPick, tags: tagsPick },
        }),
      });
      const raw = await res.text();
      try {
        const j = JSON.parse(raw) as { note?: { id: string }; error?: { message?: string } };
        if (!res.ok) {
          setErr(j.error?.message ?? "Merge failed");
          return;
        }
        if (j.note?.id) {
          onMerged(j.note.id);
          onClose();
          setOtherId("");
        }
      } catch {
        setErr("Unexpected response");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-label="Merge notes"
    >
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg border border-border-strong bg-canvas p-4 shadow-xl">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-title-3 text-secondary">Merge notes</p>
            <p className="mt-1 text-caption text-muted">
              Survivor: <span className="font-mono text-secondary">{survivorNoteId}</span>
            </p>
          </div>
          <button
            type="button"
            className="text-caption text-muted hover:text-secondary"
            onClick={onClose}
          >
            Close
          </button>
        </div>

        <label className="mt-4 block text-caption text-secondary">
          Other note id (uuid)
          <input
            className="mt-1 w-full rounded-md border border-border-strong bg-surface px-2 py-1 font-mono text-caption text-secondary"
            value={otherId}
            onChange={(e) => setOtherId(e.target.value)}
            placeholder="00000000-0000-4000-8000-000000000000"
          />
        </label>

        <fieldset className="mt-4 space-y-2 text-caption text-secondary">
          <legend className="font-medium">Keep field from</legend>
          {(
            [
              ["title", titlePick, setTitlePick],
              ["body", bodyPick, setBodyPick],
              ["tags", tagsPick, setTagsPick],
            ] as const
          ).map(([field, val, set]) => (
            <div key={field} className="flex flex-wrap gap-3">
              <span className="w-14 capitalize text-muted">{field}</span>
              <label className="flex items-center gap-1">
                <input
                  type="radio"
                  name={`${field}-pick`}
                  checked={val === "survivor"}
                  onChange={() => set("survivor")}
                />
                Survivor
              </label>
              <label className="flex items-center gap-1">
                <input
                  type="radio"
                  name={`${field}-pick`}
                  checked={val === "other"}
                  onChange={() => set("other")}
                />
                Other
              </label>
            </div>
          ))}
        </fieldset>

        {err ? (
          <p className="mt-3 text-caption text-red-300" role="alert">
            {err}
          </p>
        ) : null}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            className="rounded-md border border-border-strong px-3 py-1.5 text-caption text-secondary"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={busy || !otherId.trim()}
            className="rounded-md bg-accent-primary px-3 py-1.5 text-caption font-medium text-canvas disabled:opacity-50"
            onClick={() => void submit()}
          >
            {busy ? "Merging…" : "Merge"}
          </button>
        </div>
      </div>
    </div>
  );
}
