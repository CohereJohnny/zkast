"use client";

import { useState } from "react";

export type IncidentEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  fact: string;
  valid_from: string | null;
  valid_to: string | null;
  origin: string;
  is_user_edited: boolean;
};

function otherEndpoint(edge: IncidentEdge, entityId: string): string {
  return edge.source === entityId ? edge.target : edge.source;
}

export function GraphEdgePopover({
  workspaceId,
  entityId,
  edges,
  onChanged,
}: {
  workspaceId: string;
  entityId: string;
  edges: IncidentEdge[];
  onChanged: () => void;
}) {
  const [edgeTarget, setEdgeTarget] = useState("");
  const [edgeType, setEdgeType] = useState("RELATED_TO");
  const [edgeFact, setEdgeFact] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [editType, setEditType] = useState("");
  const [editFact, setEditFact] = useState("");
  const [editValidTo, setEditValidTo] = useState("");
  const [editBusy, setEditBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const parseErr = (raw: string) => {
    try {
      const j = JSON.parse(raw) as { detail?: { error?: { message?: string } }; error?: { message?: string } };
      return j.detail && typeof j.detail === "object" && "error" in j.detail
        ? (j.detail as { error?: { message?: string } }).error?.message
        : j.error?.message;
    } catch {
      return null;
    }
  };

  const createEdge = async () => {
    if (!edgeTarget.trim()) return;
    setCreateBusy(true);
    setErr(null);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/graph/relationships`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_entity_id: entityId,
          target_entity_id: edgeTarget.trim(),
          type: edgeType.trim() || "RELATED_TO",
          fact: edgeFact.trim(),
        }),
      });
      const raw = await res.text();
      if (!res.ok) {
        setErr(parseErr(raw) ?? "Failed to add edge");
        return;
      }
      setEdgeTarget("");
      setEdgeFact("");
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to add edge");
    } finally {
      setCreateBusy(false);
    }
  };

  const startEdit = (e: IncidentEdge) => {
    setEditId(e.id);
    setEditType(e.type);
    setEditFact(e.fact ?? "");
    setEditValidTo(e.valid_to ? e.valid_to.slice(0, 16) : "");
  };

  const saveEdit = async () => {
    if (!editId) return;
    setEditBusy(true);
    setErr(null);
    try {
      const body: Record<string, string> = {};
      const t = editType.trim();
      if (t) body.type = t;
      body.fact = editFact;
      if (editValidTo.trim()) {
        body.valid_to = new Date(editValidTo).toISOString();
      }
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/graph/relationships/${editId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const raw = await res.text();
      if (!res.ok) {
        setErr(parseErr(raw) ?? "Update failed");
        return;
      }
      setEditId(null);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Update failed");
    } finally {
      setEditBusy(false);
    }
  };

  const endEdge = async (id: string) => {
    setErr(null);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/graph/relationships/${id}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) {
        const raw = await res.text();
        setErr(parseErr(raw) ?? "End edge failed");
        return;
      }
      if (editId === id) setEditId(null);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "End edge failed");
    }
  };

  return (
    <div className="mt-4 space-y-4 border-t border-border pt-3 text-caption">
      <p className="font-medium text-muted-foreground">Relationships</p>
      {err ? <p className="text-red-300">{err}</p> : null}

      <div>
        <p className="text-muted-foreground">Incident edges</p>
        {edges.length === 0 ? (
          <p className="mt-1 text-muted-foreground">None</p>
        ) : (
          <ul className="mt-1 max-h-40 space-y-2 overflow-y-auto">
            {edges.map((e) => (
              <li key={e.id} className="rounded border border-border p-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono text-[10px] text-muted-foreground">{e.id.slice(0, 8)}…</span>
                  {e.valid_to ? <span className="text-amber-200/90">ended</span> : null}
                </div>
                <p className="text-muted-foreground">
                  → <span className="font-mono">{otherEndpoint(e, entityId).slice(0, 8)}…</span> · {e.type}
                </p>
                {e.fact ? <p className="text-muted-foreground">{e.fact}</p> : null}
                <div className="mt-1 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="text-primary underline"
                    onClick={() => startEdit(e)}
                    disabled={Boolean(e.valid_to)}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="text-muted-foreground underline"
                    onClick={() => void endEdge(e.id)}
                    disabled={Boolean(e.valid_to)}
                  >
                    End
                  </button>
                </div>
                {editId === e.id ? (
                  <div className="mt-2 space-y-2 border-t border-border pt-2">
                    <label className="block text-muted-foreground">
                      Type
                      <input
                        className="mt-1 w-full rounded border border-input bg-background px-2 py-1"
                        value={editType}
                        onChange={(ev) => setEditType(ev.target.value)}
                      />
                    </label>
                    <label className="block text-muted-foreground">
                      Fact
                      <input
                        className="mt-1 w-full rounded border border-input bg-background px-2 py-1"
                        value={editFact}
                        onChange={(ev) => setEditFact(ev.target.value)}
                      />
                    </label>
                    <label className="block text-muted-foreground">
                      Valid to (local, optional)
                      <input
                        type="datetime-local"
                        className="mt-1 w-full rounded border border-input bg-background px-2 py-1"
                        value={editValidTo}
                        onChange={(ev) => setEditValidTo(ev.target.value)}
                      />
                    </label>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        disabled={editBusy}
                        className="rounded bg-primary px-2 py-1 text-primary-foreground disabled:opacity-50"
                        onClick={() => void saveEdit()}
                      >
                        {editBusy ? "…" : "Save"}
                      </button>
                      <button type="button" className="rounded border border-input px-2 py-1" onClick={() => setEditId(null)}>
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <p className="font-medium text-muted-foreground">Add edge (manual)</p>
        <label className="mt-1 block text-muted-foreground">
          Target entity UUID
          <input
            className="mt-1 w-full rounded border border-input bg-background px-2 py-1 font-mono"
            value={edgeTarget}
            onChange={(e) => setEdgeTarget(e.target.value)}
            placeholder="Target entity id"
          />
        </label>
        <label className="mt-1 block text-muted-foreground">
          Relationship type
          <input
            className="mt-1 w-full rounded border border-input bg-background px-2 py-1"
            value={edgeType}
            onChange={(e) => setEdgeType(e.target.value)}
          />
        </label>
        <label className="mt-1 block text-muted-foreground">
          Fact (optional)
          <input
            className="mt-1 w-full rounded border border-input bg-background px-2 py-1"
            value={edgeFact}
            onChange={(e) => setEdgeFact(e.target.value)}
          />
        </label>
        <button
          type="button"
          disabled={createBusy || !edgeTarget.trim()}
          className="mt-2 rounded bg-primary px-2 py-1 font-medium text-primary-foreground disabled:opacity-50"
          onClick={() => void createEdge()}
        >
          {createBusy ? "…" : "Create edge"}
        </button>
      </div>
    </div>
  );
}
