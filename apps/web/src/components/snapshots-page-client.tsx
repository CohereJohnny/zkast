"use client";

import { useCallback, useEffect, useState } from "react";

import { useConfirm, useToast } from "@/components/feedback-provider";

type SnapshotRow = {
  id: string;
  name: string;
  description: string | null;
  stats: { entity_count?: number; relationship_count?: number; note_count?: number };
  created_at: string;
};

export function SnapshotsPageClient({ workspaceId }: { workspaceId: string }) {
  const [items, setItems] = useState<SnapshotRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const confirm = useConfirm();

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/snapshots`, { cache: "no-store" });
      const body = (await res.json()) as {
        items?: SnapshotRow[];
        total?: number;
        error?: { message?: string };
      };
      if (!res.ok) {
        setError(body.error?.message ?? "Failed to load snapshots");
        setItems([]);
        return;
      }
      setItems(body.items ?? []);
      setTotal(body.total ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/snapshots`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), description: description.trim() || null }),
      });
      const raw = await res.text();
      if (!res.ok) {
        try {
          const j = JSON.parse(raw) as { detail?: { error?: { message?: string } }; error?: { message?: string } };
          const msg =
            j.detail && typeof j.detail === "object" && "error" in j.detail
              ? (j.detail as { error?: { message?: string } }).error?.message
              : j.error?.message;
          setError(msg ?? "Create failed");
        } catch {
          setError("Create failed");
        }
        setBusy(false);
        return;
      }
      setOpen(false);
      setName("");
      setDescription("");
      await load();
      toast({ variant: "success", message: "Snapshot created", description: name.trim() });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    } finally {
      setBusy(false);
    }
  };

  const review = async (id: string, decision: "approved" | "rejected") => {
    const res = await fetch(`/api/v1/workspaces/${workspaceId}/snapshots/${id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
    });
    if (res.ok) {
      toast({
        variant: "success",
        message: decision === "approved" ? "Snapshot approved" : "Snapshot rejected",
      });
    } else {
      toast({ variant: "error", message: "Review failed" });
    }
  };

  const remove = async (id: string, snapshotName: string) => {
    const ok = await confirm({
      title: "Delete snapshot?",
      description: `“${snapshotName}” will be permanently removed. This cannot be undone.`,
      confirmLabel: "Delete",
      variant: "danger",
    });
    if (!ok) return;
    const res = await fetch(`/api/v1/workspaces/${workspaceId}/snapshots/${id}`, { method: "DELETE" });
    if (res.ok) {
      await load();
      toast({ variant: "success", message: "Snapshot deleted" });
    } else {
      toast({ variant: "error", message: "Could not delete snapshot" });
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-4">
      <header>
        <h1 className="text-title-2 text-secondary">Snapshots</h1>
        <p className="mt-1 text-body text-muted">
          Freeze the working graph for a named checkpoint. Snapshots are immutable; the live graph keeps changing.
        </p>
      </header>
      {error ? (
        <p className="text-caption text-red-300" role="alert">
          {error}
        </p>
      ) : null}
      <button
        type="button"
        className="rounded-md bg-accent-primary px-4 py-2 text-body font-medium text-canvas"
        onClick={() => setOpen(true)}
      >
        Create snapshot
      </button>
      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Create snapshot"
        >
          <div className="w-full max-w-md rounded-lg border border-border-strong bg-surface p-4 shadow-xl">
            <p className="text-body font-medium text-secondary">New snapshot</p>
            <label className="mt-3 block text-caption text-muted">
              Name (unique per workspace)
              <input
                className="mt-1 w-full rounded border border-border-strong bg-canvas px-2 py-1 text-secondary"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={120}
              />
            </label>
            <label className="mt-2 block text-caption text-muted">
              Description (optional)
              <textarea
                className="mt-1 w-full rounded border border-border-strong bg-canvas px-2 py-1 text-secondary"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                maxLength={1000}
              />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                className="rounded border border-border-strong px-3 py-1 text-caption text-secondary"
                onClick={() => setOpen(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={busy || !name.trim()}
                className="rounded bg-accent-primary px-3 py-1 text-caption font-medium text-canvas disabled:opacity-50"
                onClick={() => void create()}
              >
                {busy ? "…" : "Create"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      <section aria-label="Snapshot list">
        {loading ? (
          <p className="text-caption text-muted">Loading…</p>
        ) : items.length === 0 ? (
          <p className="text-caption text-muted">No snapshots yet.</p>
        ) : (
          <ul className="divide-y divide-border-subtle rounded-lg border border-border-subtle">
            {items.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-body font-medium text-secondary">{s.name}</p>
                  <p className="text-caption text-muted">
                    {new Date(s.created_at).toLocaleString()} · entities {s.stats?.entity_count ?? 0} · rels{" "}
                    {s.stats?.relationship_count ?? 0} · notes {s.stats?.note_count ?? 0}
                  </p>
                  {s.description ? <p className="mt-1 text-caption text-secondary">{s.description}</p> : null}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    className="rounded-md border border-border-strong px-2 py-1 text-caption text-secondary transition-colors duration-150 hover:bg-surface-raised"
                    onClick={() => void review(s.id, "approved")}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    className="rounded-md border border-border-strong px-2 py-1 text-caption text-secondary transition-colors duration-150 hover:bg-surface-raised"
                    onClick={() => void review(s.id, "rejected")}
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    className="rounded text-caption text-danger underline transition-colors duration-150 hover:opacity-80 focus:outline-none focus-visible:ring-2 focus-visible:ring-danger"
                    onClick={() => void remove(s.id, s.name)}
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {!loading ? <p className="mt-2 text-caption text-muted">Total: {total}</p> : null}
      </section>
    </div>
  );
}
