"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useConfirm, useToast } from "@/components/feedback-provider";
import { DocumentPicker } from "@/components/filters/document-picker";
import { EntityTypeahead } from "@/components/filters/entity-typeahead";
import { TagPicker } from "@/components/filters/tag-picker";
import { TypeMultiselect } from "@/components/filters/type-multiselect";
import { emitGraphInvalidated } from "@/lib/graph-events";

export type GraphFilterValues = Record<string, string | undefined>;

export function GraphFilterBar({
  basePath,
  workspaceId,
}: {
  basePath: string;
  workspaceId?: string;
}) {
  const router = useRouter();
  const sp = useSearchParams();
  const [documentId, setDocumentId] = useState(sp.get("document_id") ?? "");
  const [tag, setTag] = useState(sp.get("tag") ?? "");
  const [entityTypes, setEntityTypes] = useState(sp.get("entity_types") ?? "");
  const [edgeTypes, setEdgeTypes] = useState(sp.get("edge_types") ?? "");
  const [view, setView] = useState(sp.get("view") ?? "overview");
  const [seeds, setSeeds] = useState(sp.getAll("seed_entity_ids").join(","));

  const apply = useCallback(() => {
    const p = new URLSearchParams(sp.toString());
    const setOrDel = (k: string, v: string) => {
      const t = v.trim();
      if (t) p.set(k, t);
      else p.delete(k);
    };
    p.delete("seed_entity_ids");
    seeds
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
      .forEach((s) => p.append("seed_entity_ids", s));
    setOrDel("document_id", documentId);
    setOrDel("tag", tag);
    setOrDel("entity_types", entityTypes);
    setOrDel("edge_types", edgeTypes);
    setOrDel("view", view);
    router.push(`${basePath}?${p.toString()}`);
  }, [router, sp, basePath, documentId, tag, entityTypes, edgeTypes, view, seeds]);

  // D5 — debounce the chip-style filters (entity types, edge types, tag) so
  // typing applies after a short pause without forcing an "Apply" click.
  // The graph canvas handles these client-side as hidden attributes; the
  // URL push is what feeds searchParamsToGraphFilters → GraphCanvas.
  // Heavier filters (view / seeds / document_id / valid_at / node_limit /
  // depth) intentionally still require the Apply button — they trigger a
  // refetch + relayout.
  const initialChipsRef = useRef(true);
  useEffect(() => {
    if (initialChipsRef.current) {
      initialChipsRef.current = false;
      return;
    }
    const timer = window.setTimeout(() => {
      const p = new URLSearchParams(sp.toString());
      const setOrDel = (k: string, v: string) => {
        const t = v.trim();
        if (t) p.set(k, t);
        else p.delete(k);
      };
      setOrDel("entity_types", entityTypes);
      setOrDel("edge_types", edgeTypes);
      setOrDel("tag", tag);
      router.replace(`${basePath}?${p.toString()}`);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [entityTypes, edgeTypes, tag, basePath, router, sp]);

  const clear = useCallback(() => {
    setDocumentId("");
    setTag("");
    setEntityTypes("");
    setEdgeTypes("");
    setView("overview");
    setSeeds("");
    router.push(basePath);
  }, [router, basePath]);

  const [cleanupBusy, setCleanupBusy] = useState(false);
  const toast = useToast();
  const confirm = useConfirm();

  const cleanupOrphans = useCallback(async () => {
    if (!workspaceId) return;
    const ok = await confirm({
      title: "Clean orphan graph rows?",
      description:
        "Removes entities and relationships that no longer have any document or note backing them. User-edited entities and manual edges are preserved.",
      confirmLabel: "Clean orphans",
      variant: "danger",
    });
    if (!ok) return;
    setCleanupBusy(true);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/graph/cleanup-orphans`, {
        method: "POST",
      });
      const raw = await res.text();
      try {
        const j = JSON.parse(raw) as {
          removed_entities?: number;
          removed_relationships?: number;
          error?: { message?: string };
        };
        if (!res.ok) {
          toast({
            variant: "error",
            message: "Cleanup failed",
            description: j.error?.message ?? `Server returned ${res.status}`,
          });
          return;
        }
        const ent = j.removed_entities ?? 0;
        const rel = j.removed_relationships ?? 0;
        toast({
          variant: ent + rel === 0 ? "info" : "success",
          message:
            ent + rel === 0
              ? "Graph already clean"
              : `Removed ${ent} ${ent === 1 ? "entity" : "entities"} and ${rel} ${rel === 1 ? "relationship" : "relationships"}`,
        });
        emitGraphInvalidated();
      } catch {
        toast({ variant: "error", message: "Unexpected cleanup response" });
      }
    } finally {
      setCleanupBusy(false);
    }
  }, [workspaceId, confirm, toast]);

  const chips = useMemo(() => {
    const out: string[] = [];
    if (documentId.trim()) out.push(`doc`);
    if (tag.trim()) out.push(`tag`);
    if (entityTypes.trim()) out.push(`entityTypes`);
    if (edgeTypes.trim()) out.push(`edgeTypes`);
    if (view !== "overview") out.push(view);
    if (seeds.trim()) out.push("subgraph");
    return out;
  }, [documentId, tag, entityTypes, edgeTypes, view, seeds]);

  return (
    <div className="flex flex-col gap-2 border-b border-border-subtle pb-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-caption font-medium text-secondary">Graph filters</span>
        {chips.length ? (
          <span className="text-caption text-muted">({chips.join(" · ")})</span>
        ) : null}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="text-caption text-muted">
          View
          <select
            className="mt-1 w-full cursor-pointer rounded border border-border-strong bg-surface px-2 py-1 text-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-primary"
            value={view}
            onChange={(e) => setView(e.target.value)}
          >
            <option value="overview">Overview</option>
            <option value="subgraph">Subgraph</option>
          </select>
        </label>
        {workspaceId ? (
          <EntityTypeahead
            workspaceId={workspaceId}
            value={seeds}
            onChange={setSeeds}
          />
        ) : (
          <p className="text-caption text-muted">Seed entities (workspace loading…)</p>
        )}
        {workspaceId ? (
          <DocumentPicker
            workspaceId={workspaceId}
            value={documentId}
            onChange={setDocumentId}
          />
        ) : (
          <p className="text-caption text-muted">Document (workspace loading…)</p>
        )}
        {workspaceId ? (
          <TagPicker workspaceId={workspaceId} value={tag} onChange={setTag} />
        ) : (
          <p className="text-caption text-muted">Tag (workspace loading…)</p>
        )}
        {workspaceId ? (
          <TypeMultiselect
            workspaceId={workspaceId}
            kind="entity_types"
            value={entityTypes}
            onChange={setEntityTypes}
            label="Entity types"
          />
        ) : null}
        {workspaceId ? (
          <TypeMultiselect
            workspaceId={workspaceId}
            kind="edge_types"
            value={edgeTypes}
            onChange={setEdgeTypes}
            label="Edge types"
          />
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="rounded-md bg-accent-primary px-3 py-1 text-caption font-medium text-canvas"
          onClick={() => void apply()}
        >
          Apply filters
        </button>
        <button
          type="button"
          className="rounded-md border border-border-strong px-3 py-1 text-caption text-secondary"
          onClick={() => void clear()}
        >
          Clear
        </button>
        {workspaceId ? (
          <button
            type="button"
            disabled={cleanupBusy}
            title="Remove entities and relationships with no remaining document or note provenance"
            className="ml-auto rounded-md border border-border-subtle px-3 py-1 text-caption text-muted transition-colors duration-150 hover:bg-surface-raised hover:text-secondary disabled:opacity-50"
            onClick={() => void cleanupOrphans()}
          >
            {cleanupBusy ? "Cleaning…" : "Clean orphan rows"}
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function searchParamsToGraphFilters(sp: URLSearchParams): GraphFilterValues {
  const seeds = sp.getAll("seed_entity_ids").join(",");
  return {
    view: sp.get("view") ?? "overview",
    document_id: sp.get("document_id") ?? undefined,
    tag: sp.get("tag") ?? undefined,
    entity_types: sp.get("entity_types") ?? undefined,
    edge_types: sp.get("edge_types") ?? undefined,
    valid_at: sp.get("valid_at") ?? undefined,
    node_limit: sp.get("node_limit") ?? undefined,
    depth: sp.get("depth") ?? undefined,
    seed_entity_ids: seeds || undefined,
  };
}
