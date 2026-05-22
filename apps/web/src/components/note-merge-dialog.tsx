"use client";

import { useCallback, useEffect, useState } from "react";

type NoteSnap = { title: string; body: string; tags: string[] };

async function fetchNote(workspaceId: string, noteId: string): Promise<NoteSnap | null> {
  const res = await fetch(`/api/v1/workspaces/${workspaceId}/notes/${noteId}`, { cache: "no-store" });
  const body = (await res.json()) as { note?: NoteSnap };
  if (!res.ok || !body.note) return null;
  return {
    title: body.note.title,
    body: body.note.body,
    tags: body.note.tags ?? [],
  };
}

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
  const [survivorBefore, setSurvivorBefore] = useState<NoteSnap | null>(null);
  const [showUndo, setShowUndo] = useState(false);

  const loadSurvivor = useCallback(async () => {
    const snap = await fetchNote(workspaceId, survivorNoteId);
    setSurvivorBefore(snap);
  }, [workspaceId, survivorNoteId]);

  useEffect(() => {
    if (!open) {
      setShowUndo(false);
      setErr(null);
      setOtherId("");
      return;
    }
    void loadSurvivor();
  }, [open, loadSurvivor]);

  if (!open) return null;

  const fullUndo = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/notes/${survivorNoteId}/unmerge`,
        { method: "POST" },
      );
      const raw = await res.text();
      if (!res.ok) {
        try {
          const j = JSON.parse(raw) as { error?: { message?: string } };
          setErr(j.error?.message ?? "Undo failed");
        } catch {
          setErr("Undo failed");
        }
        setBusy(false);
        return;
      }
      setShowUndo(false);
      onMerged(survivorNoteId);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Undo failed");
    } finally {
      setBusy(false);
    }
  };

  const revertSurvivorFields = async () => {
    if (!survivorBefore) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/notes/${survivorNoteId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: survivorBefore.title,
          body: survivorBefore.body,
          tags: survivorBefore.tags,
        }),
      });
      const raw = await res.text();
      if (!res.ok) {
        try {
          const j = JSON.parse(raw) as { error?: { message?: string } };
          setErr(j.error?.message ?? "Revert failed");
        } catch {
          setErr("Revert failed");
        }
        setBusy(false);
        return;
      }
      setShowUndo(false);
      onMerged(survivorNoteId);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Revert failed");
    } finally {
      setBusy(false);
    }
  };

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
          setShowUndo(true);
          onMerged(j.note.id);
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
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg border border-input bg-background p-4 shadow-xl">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-h5 text-muted-foreground">Merge notes</p>
            <p className="mt-1 text-caption text-muted-foreground">
              Survivor: <span className="font-mono text-muted-foreground">{survivorNoteId}</span>
            </p>
          </div>
          <button
            type="button"
            className="text-caption text-muted-foreground hover:text-muted-foreground"
            onClick={onClose}
          >
            Close
          </button>
        </div>

        {showUndo ? (
          <div className="mt-4 space-y-3 text-caption text-muted-foreground">
            <p>
              Merge completed. The other note was removed. Choose either:
            </p>
            <ul className="ml-4 list-disc space-y-1 text-muted-foreground">
              <li>
                <strong className="text-muted-foreground">Full undo</strong> &mdash; restore the merged note row and re-attach its provenance.
              </li>
              <li>
                <strong className="text-muted-foreground">Revert survivor fields</strong> &mdash; keep the merge but roll back this note&rsquo;s title,
                body and tags.
              </li>
            </ul>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                className="rounded-md bg-destructive px-3 py-1.5 font-medium text-white transition-colors duration-150 hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-destructive focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-50"
                onClick={() => void fullUndo()}
              >
                {busy ? "…" : "Full undo"}
              </button>
              <button
                type="button"
                disabled={busy || !survivorBefore}
                className="rounded-md border border-input px-3 py-1.5 text-muted-foreground transition-colors duration-150 hover:bg-secondary disabled:opacity-50"
                onClick={() => void revertSurvivorFields()}
              >
                {busy ? "…" : "Revert survivor fields"}
              </button>
              <button
                type="button"
                className="rounded-md bg-primary px-3 py-1.5 font-medium text-primary-foreground"
                onClick={onClose}
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <>
            <label className="mt-4 block text-caption text-muted-foreground">
              Other note id (uuid)
              <input
                className="mt-1 w-full rounded-md border border-input bg-card px-2 py-1 font-mono text-caption text-muted-foreground"
                value={otherId}
                onChange={(e) => setOtherId(e.target.value)}
                placeholder="00000000-0000-4000-8000-000000000000"
              />
            </label>

            <fieldset className="mt-4 space-y-2 text-caption text-muted-foreground">
              <legend className="font-medium">Keep field from</legend>
              {(
                [
                  ["title", titlePick, setTitlePick],
                  ["body", bodyPick, setBodyPick],
                  ["tags", tagsPick, setTagsPick],
                ] as const
              ).map(([field, val, set]) => (
                <div key={field} className="flex flex-wrap gap-3">
                  <span className="w-14 capitalize text-muted-foreground">{field}</span>
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
          </>
        )}

        {err ? (
          <p className="mt-3 text-caption text-red-300" role="alert">
            {err}
          </p>
        ) : null}

        {!showUndo ? (
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              className="rounded-md border border-input px-3 py-1.5 text-caption text-muted-foreground"
              onClick={onClose}
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={busy || !otherId.trim()}
              className="rounded-md bg-primary px-3 py-1.5 text-caption font-medium text-primary-foreground disabled:opacity-50"
              onClick={() => void submit()}
            >
              {busy ? "Merging…" : "Merge"}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
