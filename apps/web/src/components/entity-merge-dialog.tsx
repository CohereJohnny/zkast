"use client";

import { useCallback, useEffect, useState } from "react";

type FieldPick = "survivor" | "other";

type SurvivorSnapshot = {
  canonical_name: string;
  type: string;
  summary: string;
  aliases: string[];
  properties: Record<string, unknown>;
};

async function fetchEntity(
  workspaceId: string,
  entityId: string,
): Promise<SurvivorSnapshot | null> {
  const res = await fetch(
    `/api/v1/workspaces/${workspaceId}/graph/entities/${entityId}?neighbor_depth=0&neighbor_limit=1`,
    { cache: "no-store" },
  );
  const body = (await res.json()) as {
    entity?: SurvivorSnapshot & { name?: string; canonical_name?: string };
  };
  if (!res.ok || !body.entity) return null;
  const e = body.entity;
  return {
    canonical_name: (e.name ?? e.canonical_name ?? "").trim(),
    type: e.type,
    summary: e.summary ?? "",
    aliases: e.aliases ?? [],
    properties: (e.properties ?? {}) as Record<string, unknown>,
  };
}

export function EntityMergeDialog({
  open,
  workspaceId,
  survivorEntityId,
  onClose,
  onMerged,
}: {
  open: boolean;
  workspaceId: string;
  survivorEntityId: string;
  onClose: () => void;
  onMerged: () => void;
}) {
  const [otherId, setOtherId] = useState("");
  const [canonicalPick, setCanonicalPick] = useState<FieldPick>("survivor");
  const [typePick, setTypePick] = useState<FieldPick>("survivor");
  const [aliasesPick, setAliasesPick] = useState<FieldPick>("survivor");
  const [summaryPick, setSummaryPick] = useState<FieldPick>("survivor");
  const [propertiesPick, setPropertiesPick] = useState<FieldPick>("survivor");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [survivorBefore, setSurvivorBefore] = useState<SurvivorSnapshot | null>(null);
  const [showUndo, setShowUndo] = useState(false);

  const loadSurvivor = useCallback(async () => {
    const snap = await fetchEntity(workspaceId, survivorEntityId);
    setSurvivorBefore(snap);
  }, [workspaceId, survivorEntityId]);

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

  const revertSurvivorFields = async () => {
    if (!survivorBefore) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/graph/entities/${survivorEntityId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          canonical_name: survivorBefore.canonical_name,
          type: survivorBefore.type,
          summary: survivorBefore.summary,
          aliases: survivorBefore.aliases,
          properties: survivorBefore.properties,
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
      onMerged();
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Revert failed");
    } finally {
      setBusy(false);
    }
  };

  const fullUndo = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/graph/entities/${survivorEntityId}/unmerge`,
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
      onMerged();
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Undo failed");
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    setErr(null);
    setBusy(true);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/graph/entities/${survivorEntityId}/merge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          other_entity_id: otherId.trim(),
          field_selection: {
            canonical_name: canonicalPick,
            type: typePick,
            aliases: aliasesPick,
            summary: summaryPick,
            properties: propertiesPick,
          },
        }),
      });
      const raw = await res.text();
      try {
        const j = JSON.parse(raw) as { error?: { message?: string } };
        if (!res.ok) {
          setErr(j.error?.message ?? "Merge failed");
          return;
        }
        setShowUndo(true);
        onMerged();
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
      aria-label="Merge entities"
    >
      <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg border border-input bg-background p-4 shadow-xl">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-h5 text-muted-foreground">Merge entities</p>
            <p className="mt-1 text-caption text-muted-foreground">
              Survivor: <span className="font-mono text-muted-foreground">{survivorEntityId}</span>
            </p>
          </div>
          <button type="button" className="text-caption text-muted-foreground hover:text-muted-foreground" onClick={onClose}>
            Close
          </button>
        </div>

        {showUndo ? (
          <div className="mt-4 space-y-3 text-caption text-muted-foreground">
            <p>
              Merge completed. The other entity row was removed from the working graph. Choose either:
            </p>
            <ul className="ml-4 list-disc space-y-1 text-muted-foreground">
              <li>
                <strong className="text-muted-foreground">Full undo</strong> — restore the merged entity row and re-attach its provenance.
              </li>
              <li>
                <strong className="text-muted-foreground">Revert survivor fields</strong> — keep the merge but roll back this entity&rsquo;s field
                values (name, type, summary, aliases, properties).
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
              Other entity id (uuid)
              <input
                className="mt-1 w-full rounded-md border border-input bg-card px-2 py-1 font-mono text-caption text-muted-foreground"
                value={otherId}
                onChange={(e) => setOtherId(e.target.value)}
                placeholder="Victim entity id (merged into survivor)"
              />
            </label>

            <fieldset className="mt-4 space-y-2 text-caption text-muted-foreground">
              <legend className="font-medium">Keep field from</legend>
              {(
                [
                  ["canonical name", canonicalPick, setCanonicalPick],
                  ["type", typePick, setTypePick],
                  ["aliases", aliasesPick, setAliasesPick],
                  ["summary", summaryPick, setSummaryPick],
                  ["properties", propertiesPick, setPropertiesPick],
                ] as const
              ).map(([label, val, set]) => (
                <div key={label} className="flex flex-wrap gap-3">
                  <span className="min-w-[6rem] text-muted-foreground">{label}</span>
                  <label className="flex items-center gap-1">
                    <input type="radio" name={`pick-${label}`} checked={val === "survivor"} onChange={() => set("survivor")} />
                    Survivor
                  </label>
                  <label className="flex items-center gap-1">
                    <input type="radio" name={`pick-${label}`} checked={val === "other"} onChange={() => set("other")} />
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
