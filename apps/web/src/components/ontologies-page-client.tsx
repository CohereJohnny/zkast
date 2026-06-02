"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useToast } from "@/components/feedback-provider";
import {
  SourceScopeFilter,
  type SourceScopeSelection,
} from "@/components/filters/source-scope-filter";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type PromptSetSummary = {
  id: string;
  name: string;
  version: string;
  origin: string;
  is_builtin: boolean;
  derived_from_version?: string | null;
  created_at?: string | null;
};

type OntField = {
  name: string;
  description?: string | null;
  optional?: boolean;
  default?: unknown;
};

type OntType = {
  name: string;
  title?: string | null;
  description: string;
  fields: OntField[];
};

type EdgeMapEntry = { subject: string; object: string; edges: string[] };

type OntologyDoc = {
  name: string;
  version: string;
  origin: string;
  is_builtin: boolean;
  entity_types: OntType[];
  edge_types: OntType[];
  edge_type_map: EdgeMapEntry[];
  instructions: string;
};

function originVariant(origin: string): "info" | "secondary" | "success" {
  if (origin === "generic") return "info";
  if (origin === "auto") return "success";
  return "secondary";
}

export function OntologiesPageClient({ workspaceId }: { workspaceId: string }) {
  const toast = useToast();
  const base = `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/prompt-sets`;

  const [items, setItems] = useState<PromptSetSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detail, setDetail] = useState<OntologyDoc | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // Editor state.
  const [editorOpen, setEditorOpen] = useState(false);
  const [editName, setEditName] = useState("");
  const [editVersion, setEditVersion] = useState("");
  const [editBody, setEditBody] = useState("");
  const [derivedFrom, setDerivedFrom] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  // Auto-tune state.
  const [autotuneOpen, setAutotuneOpen] = useState(false);
  const [atName, setAtName] = useState("");
  const [atVersion, setAtVersion] = useState("v1");
  const [atSample, setAtSample] = useState(40);
  const [atScope, setAtScope] = useState<SourceScopeSelection | null>(null);
  const [atBusy, setAtBusy] = useState(false);
  const [atErrors, setAtErrors] = useState<string[]>([]);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(base, { cache: "no-store" });
      const body = (await res.json()) as { items?: PromptSetSummary[]; error?: { message?: string } };
      if (!res.ok) {
        toast({ variant: "error", message: body.error?.message ?? "Failed to load ontologies" });
        return;
      }
      setItems(body.items ?? []);
    } catch {
      toast({ variant: "error", message: "Failed to load ontologies" });
    } finally {
      setLoading(false);
    }
  }, [base, toast]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const openDetail = useCallback(
    async (name: string, version: string) => {
      const key = `${name}/${version}`;
      setSelectedKey(key);
      setEditorOpen(false);
      setLoadingDetail(true);
      setDetail(null);
      try {
        const res = await fetch(
          `${base}/${encodeURIComponent(name)}/${encodeURIComponent(version)}`,
          { cache: "no-store" },
        );
        const body = (await res.json()) as OntologyDoc & { error?: { message?: string } };
        if (!res.ok) {
          toast({ variant: "error", message: body.error?.message ?? "Failed to load ontology" });
          return;
        }
        setDetail(body);
      } catch {
        toast({ variant: "error", message: "Failed to load ontology" });
      } finally {
        setLoadingDetail(false);
      }
    },
    [base, toast],
  );

  const suggestNextVersion = (version: string): string => {
    const m = version.match(/^v(\d+)$/i);
    if (m) return `v${Number(m[1]) + 1}`;
    return `${version}-copy`;
  };

  const openCloneEditor = useCallback(() => {
    if (!detail) return;
    setErrors([]);
    setEditName(detail.name);
    setEditVersion(suggestNextVersion(detail.version));
    setDerivedFrom(detail.version);
    setEditBody(
      JSON.stringify(
        {
          entity_types: detail.entity_types,
          edge_types: detail.edge_types,
          edge_type_map: detail.edge_type_map,
          instructions: detail.instructions,
        },
        null,
        2,
      ),
    );
    setEditorOpen(true);
  }, [detail]);

  const submitCreate = useCallback(async () => {
    setErrors([]);
    let parsed: Partial<OntologyDoc>;
    try {
      parsed = JSON.parse(editBody) as Partial<OntologyDoc>;
    } catch (e) {
      setErrors([`Invalid JSON: ${(e as Error).message}`]);
      return;
    }
    const payload = {
      name: editName.trim(),
      version: editVersion.trim(),
      origin: "manual" as const,
      derived_from_version: derivedFrom,
      entity_types: parsed.entity_types ?? [],
      edge_types: parsed.edge_types ?? [],
      edge_type_map: parsed.edge_type_map ?? [],
      instructions: parsed.instructions ?? "",
    };
    if (!payload.name || !payload.version) {
      setErrors(["Name and version are required."]);
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch(base, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await res.json();
      if (res.status === 201) {
        toast({ variant: "success", message: `Created ${payload.name}/${payload.version}` });
        setEditorOpen(false);
        await loadList();
        await openDetail(payload.name, payload.version);
        return;
      }
      if (res.status === 422 && body?.detail?.errors) {
        setErrors(body.detail.errors as string[]);
        return;
      }
      if (res.status === 409) {
        setErrors([typeof body?.detail === "string" ? body.detail : "Version already exists."]);
        return;
      }
      setErrors([body?.error?.message ?? body?.detail ?? "Create failed."]);
    } catch {
      setErrors(["Create failed."]);
    } finally {
      setSubmitting(false);
    }
  }, [base, editBody, editName, editVersion, derivedFrom, toast, loadList, openDetail]);

  const openAutotune = useCallback(() => {
    setAtErrors([]);
    setAtName("");
    setAtVersion("v1");
    setAtSample(40);
    setAtScope(null);
    setEditorOpen(false);
    setSelectedKey(null);
    setDetail(null);
    setAutotuneOpen(true);
  }, []);

  const submitAutotune = useCallback(async () => {
    setAtErrors([]);
    const name = atName.trim();
    const version = atVersion.trim();
    if (!name || !version) {
      setAtErrors(["Name and version are required."]);
      return;
    }
    setAtBusy(true);
    try {
      const res = await fetch(`${base}/autotune`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          version,
          sample_limit: atSample,
          agent_id: atScope?.kind === "agent" ? atScope.id : null,
          document_id: atScope?.kind === "document" ? atScope.id : null,
        }),
      });
      const body = await res.json();
      if (res.status === 201) {
        toast({
          variant: "success",
          message: `Auto-tuned ${name}/${version} (${body?.stats?.entity_types ?? "?"} entity types)`,
        });
        setAutotuneOpen(false);
        await loadList();
        await openDetail(name, version);
        return;
      }
      if (res.status === 422) {
        setAtErrors([typeof body?.detail === "string" ? body.detail : "No corpus to sample."]);
        return;
      }
      if (res.status === 502 && body?.detail?.errors) {
        setAtErrors(["Auto-tuned ontology failed validation:", ...body.detail.errors]);
        return;
      }
      if (res.status === 409) {
        setAtErrors([typeof body?.detail === "string" ? body.detail : "Version already exists."]);
        return;
      }
      if (res.status === 400) {
        setAtErrors([typeof body?.detail === "string" ? body.detail : "No Cohere API key configured."]);
        return;
      }
      setAtErrors([body?.detail?.message ?? body?.detail ?? body?.error?.message ?? "Auto-tune failed."]);
    } catch {
      setAtErrors(["Auto-tune failed."]);
    } finally {
      setAtBusy(false);
    }
  }, [base, atName, atVersion, atSample, atScope, toast, loadList, openDetail]);

  const grouped = useMemo(() => {
    const builtin = items.filter((i) => i.is_builtin);
    const custom = items.filter((i) => !i.is_builtin);
    return { builtin, custom };
  }, [items]);

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-h3 text-foreground">Ontologies</h1>
          <p className="text-p text-muted-foreground">
            Versioned extraction ontologies (entity &amp; edge types + instructions) used by the
            graph extraction stage. Versions are immutable — editing creates a new version.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={openAutotune} disabled={loading}>
            Auto-tune from corpus
          </Button>
          <Button variant="outline" size="sm" onClick={() => void loadList()} disabled={loading}>
            Refresh
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-[280px_1fr] gap-4">
        {/* List */}
        <aside className="flex flex-col gap-3 rounded-lg border border-border bg-card p-3">
          <PromptSetGroup
            label="Built-in"
            sets={grouped.builtin}
            selectedKey={selectedKey}
            onSelect={openDetail}
          />
          <PromptSetGroup
            label="Workspace"
            sets={grouped.custom}
            selectedKey={selectedKey}
            onSelect={openDetail}
            emptyHint="No custom ontologies yet. Open a built-in and clone it to a new version."
          />
          {loading && <p className="text-caption text-muted-foreground">Loading…</p>}
        </aside>

        {/* Detail / Editor */}
        <section className="min-h-[420px] rounded-lg border border-border bg-card p-4">
          {autotuneOpen && (
            <AutotuneForm
              workspaceId={workspaceId}
              name={atName}
              version={atVersion}
              sample={atSample}
              scope={atScope}
              busy={atBusy}
              errors={atErrors}
              onName={setAtName}
              onVersion={setAtVersion}
              onSample={setAtSample}
              onScope={setAtScope}
              onSubmit={() => void submitAutotune()}
              onCancel={() => setAutotuneOpen(false)}
            />
          )}

          {!autotuneOpen && !selectedKey && (
            <p className="text-p text-muted-foreground">
              Select an ontology on the left to view it, clone one to a new version, or auto-tune a
              new ontology from your corpus.
            </p>
          )}

          {selectedKey && loadingDetail && (
            <p className="text-p text-muted-foreground">Loading ontology…</p>
          )}

          {selectedKey && detail && !editorOpen && (
            <OntologyDetail detail={detail} onClone={openCloneEditor} />
          )}

          {editorOpen && (
            <OntologyEditor
              name={editName}
              version={editVersion}
              body={editBody}
              errors={errors}
              submitting={submitting}
              onName={setEditName}
              onVersion={setEditVersion}
              onBody={setEditBody}
              onSubmit={() => void submitCreate()}
              onCancel={() => setEditorOpen(false)}
            />
          )}
        </section>
      </div>
    </div>
  );
}

function PromptSetGroup({
  label,
  sets,
  selectedKey,
  onSelect,
  emptyHint,
}: {
  label: string;
  sets: PromptSetSummary[];
  selectedKey: string | null;
  onSelect: (name: string, version: string) => void;
  emptyHint?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-caption uppercase tracking-wide text-muted-foreground">{label}</p>
      {sets.length === 0 && emptyHint && (
        <p className="text-caption text-muted-foreground">{emptyHint}</p>
      )}
      {sets.map((s) => {
        const key = `${s.name}/${s.version}`;
        const active = key === selectedKey;
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => onSelect(s.name, s.version)}
            className={`flex flex-col gap-1 rounded-md border border-transparent px-2 py-2 text-left transition hover:bg-secondary ${
              active ? "bg-secondary" : ""
            }`}
          >
            <span className="flex items-center gap-2">
              <span className="text-p font-medium text-foreground">{s.name}</span>
              <span className="text-caption text-muted-foreground">{s.version}</span>
            </span>
            <Badge variant={originVariant(s.origin)} className="w-fit">
              {s.origin}
            </Badge>
          </button>
        );
      })}
    </div>
  );
}

function OntologyDetail({
  detail,
  onClone,
}: {
  detail: OntologyDoc;
  onClone: () => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-h4 text-foreground">
            {detail.name} <span className="text-muted-foreground">/ {detail.version}</span>
          </h2>
          <Badge variant={originVariant(detail.origin)}>{detail.origin}</Badge>
          {detail.is_builtin && <Badge variant="outline">built-in</Badge>}
        </div>
        <Button size="sm" onClick={onClone}>
          Clone to new version
        </Button>
      </div>

      <TypeSection title={`Entity types (${detail.entity_types.length})`} types={detail.entity_types} />
      <TypeSection title={`Edge types (${detail.edge_types.length})`} types={detail.edge_types} />

      <div>
        <p className="text-h5 text-foreground">Edge-type map ({detail.edge_type_map.length})</p>
        <ul className="mt-1 flex flex-col gap-1">
          {detail.edge_type_map.map((e, i) => (
            <li key={i} className="text-p text-muted-foreground">
              <span className="text-foreground">{e.subject}</span> →{" "}
              <span className="text-foreground">{e.object}</span>: {e.edges.join(", ")}
            </li>
          ))}
        </ul>
      </div>

      <div>
        <p className="text-h5 text-foreground">Extraction instructions</p>
        <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap rounded-md bg-secondary p-3 text-caption text-foreground">
          {detail.instructions || "—"}
        </pre>
      </div>
    </div>
  );
}

function TypeSection({ title, types }: { title: string; types: OntType[] }) {
  return (
    <div>
      <p className="text-h5 text-foreground">{title}</p>
      <ul className="mt-1 flex flex-col gap-2">
        {types.map((t) => (
          <li key={t.name} className="rounded-md border border-border p-2">
            <span className="text-p font-medium text-foreground">{t.name}</span>
            <p className="text-caption text-muted-foreground">{t.description}</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {t.fields.map((f) => (
                <Badge key={f.name} variant={f.optional ? "outline" : "secondary"}>
                  {f.name}
                  {f.optional ? "?" : "*"}
                </Badge>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AutotuneForm({
  workspaceId,
  name,
  version,
  sample,
  scope,
  busy,
  errors,
  onName,
  onVersion,
  onSample,
  onScope,
  onSubmit,
  onCancel,
}: {
  workspaceId: string;
  name: string;
  version: string;
  sample: number;
  scope: SourceScopeSelection | null;
  busy: boolean;
  errors: string[];
  onName: (v: string) => void;
  onVersion: (v: string) => void;
  onSample: (v: number) => void;
  onScope: (v: SourceScopeSelection | null) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-h4 text-foreground">Auto-tune from corpus</h2>
      <p className="text-caption text-muted-foreground">
        Samples raw chunks from the selected scope and asks the LLM to propose a domain-adapted
        ontology based on <span className="text-foreground">generic / v1</span>. Saved as a new
        immutable <span className="text-foreground">auto</span> version. This runs an LLM call and
        may take up to ~30s.
      </p>

      <div>
        <SourceScopeFilter
          workspaceId={workspaceId}
          value={scope}
          onChange={onScope}
          label="Corpus scope (leave empty for the whole workspace)"
        />
        <p className="mt-1 text-caption text-muted-foreground">
          Scope to an agent or Slack channel memory space, or a single document, to generate a more
          bespoke ontology. Empty samples across the whole workspace.
        </p>
      </div>

      <div className="flex gap-3">
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-caption text-muted-foreground">Name</span>
          <Input value={name} onChange={(e) => onName(e.target.value)} placeholder="e.g. nuclear" />
        </label>
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-caption text-muted-foreground">Version</span>
          <Input value={version} onChange={(e) => onVersion(e.target.value)} placeholder="e.g. v1" />
        </label>
        <label className="flex w-32 flex-col gap-1">
          <span className="text-caption text-muted-foreground">Sample size</span>
          <Input
            type="number"
            min={4}
            max={200}
            value={sample}
            onChange={(e) => onSample(Number(e.target.value) || 40)}
          />
        </label>
      </div>

      {errors.length > 0 && (
        <ul className="flex flex-col gap-1 rounded-md border border-destructive/40 bg-destructive/10 p-2">
          {errors.map((e, i) => (
            <li key={i} className="text-caption text-destructive">
              {e}
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-2">
        <Button onClick={onSubmit} disabled={busy}>
          {busy ? "Auto-tuning…" : "Auto-tune"}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function OntologyEditor({
  name,
  version,
  body,
  errors,
  submitting,
  onName,
  onVersion,
  onBody,
  onSubmit,
  onCancel,
}: {
  name: string;
  version: string;
  body: string;
  errors: string[];
  submitting: boolean;
  onName: (v: string) => void;
  onVersion: (v: string) => void;
  onBody: (v: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-h4 text-foreground">New ontology version</h2>
      <p className="text-caption text-muted-foreground">
        Edit the entity/edge types, edge-type map, and instructions below. Each type must have a
        description and at least one required field. Saving creates a new immutable version.
      </p>

      <div className="flex gap-3">
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-caption text-muted-foreground">Name</span>
          <Input value={name} onChange={(e) => onName(e.target.value)} placeholder="e.g. nuclear" />
        </label>
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-caption text-muted-foreground">Version</span>
          <Input value={version} onChange={(e) => onVersion(e.target.value)} placeholder="e.g. v1" />
        </label>
      </div>

      <label className="flex flex-col gap-1">
        <span className="text-caption text-muted-foreground">
          Ontology body (JSON: entity_types, edge_types, edge_type_map, instructions)
        </span>
        <textarea
          value={body}
          onChange={(e) => onBody(e.target.value)}
          spellCheck={false}
          className="h-80 w-full rounded-md border border-border bg-background p-3 font-mono text-caption text-foreground"
        />
      </label>

      {errors.length > 0 && (
        <ul className="flex flex-col gap-1 rounded-md border border-destructive/40 bg-destructive/10 p-2">
          {errors.map((e, i) => (
            <li key={i} className="text-caption text-destructive">
              {e}
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-2">
        <Button onClick={onSubmit} disabled={submitting}>
          {submitting ? "Saving…" : "Save new version"}
        </Button>
        <Button variant="ghost" onClick={onCancel} disabled={submitting}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
