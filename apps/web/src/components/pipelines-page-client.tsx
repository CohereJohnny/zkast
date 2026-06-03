"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useToast } from "@/components/feedback-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Plugin = { id: string; label: string; description?: string; implemented: boolean };
type Option = { id: string; label: string };
type Stages = {
  extractors: Plugin[];
  graph_stores: Plugin[];
  retrievers: Plugin[];
  providers: Option[];
  ontology_versions: Option[];
};
type Config = {
  id: string;
  name: string;
  description?: string;
  extractor: string;
  graph_store: string;
  retrieval_strategy: string;
  ontology_version?: string | null;
  provider: string;
  version: number;
  content_hash: string;
  is_builtin: boolean;
};

function StageCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="min-w-[120px] rounded-md border border-border bg-secondary/40 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="truncate text-p font-medium text-foreground">{value}</p>
      {sub ? <p className="truncate text-caption text-muted-foreground">{sub}</p> : null}
    </div>
  );
}

function Arrow() {
  return <span className="self-center text-muted-foreground">→</span>;
}

export function PipelinesPageClient({ workspaceId }: { workspaceId: string }) {
  const toast = useToast();
  const base = `/api/v1/workspaces/${encodeURIComponent(workspaceId)}`;

  const [configs, setConfigs] = useState<Config[]>([]);
  const [stages, setStages] = useState<Stages | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  const [draft, setDraft] = useState({
    name: "",
    description: "",
    extractor: "graphiti",
    graph_store: "graphiti_falkor",
    retrieval_strategy: "graph",
    ontology_version: "generic_v1",
    provider: "cohere_compat",
  });

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [cRes, sRes] = await Promise.all([
        fetch(`${base}/pipeline-configurations`, { cache: "no-store" }),
        fetch(`${base}/pipeline-stages`, { cache: "no-store" }),
      ]);
      if (cRes.ok) setConfigs(((await cRes.json()) as { items?: Config[] }).items ?? []);
      if (sRes.ok) setStages((await sRes.json()) as Stages);
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const submit = useCallback(async () => {
    setErrors([]);
    if (!draft.name.trim()) {
      setErrors(["Name is required."]);
      return;
    }
    setBusy(true);
    try {
      const res = await fetch(`${base}/pipeline-configurations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...draft, name: draft.name.trim() }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.status === 201) {
        toast({ variant: "success", message: `Created configuration "${draft.name.trim()}"` });
        setCreating(false);
        setDraft((d) => ({ ...d, name: "", description: "" }));
        await reload();
        return;
      }
      if (res.status === 422 && body?.detail?.errors) {
        setErrors(body.detail.errors as string[]);
        return;
      }
      setErrors([typeof body?.detail === "string" ? body.detail : body?.error?.message ?? "Create failed."]);
    } finally {
      setBusy(false);
    }
  }, [base, draft, toast, reload]);

  const Select = ({
    label,
    value,
    options,
    onChange,
  }: {
    label: string;
    value: string;
    options: { id: string; label: string; implemented?: boolean }[];
    onChange: (v: string) => void;
  }) => (
    <label className="flex flex-col gap-1 text-caption text-muted-foreground">
      {label}
      <select
        className="rounded-md border border-input bg-card px-2 py-1.5 text-p text-foreground"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.id} value={o.id} disabled={o.implemented === false}>
            {o.label}
            {o.implemented === false ? " (planned)" : ""}
          </option>
        ))}
      </select>
    </label>
  );

  const pluginOpts = (ps?: Plugin[]) =>
    (ps ?? []).map((p) => ({ id: p.id, label: p.label, implemented: p.implemented }));

  const ontologyName = useMemo(() => {
    const m: Record<string, string> = {};
    for (const o of stages?.ontology_versions ?? []) m[o.id] = o.label;
    return m;
  }, [stages]);

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-start justify-between">
        <div>
          <h1 className="text-h3 text-foreground">Pipelines</h1>
          <p className="max-w-2xl text-p text-muted-foreground">
            Named, versioned compositions of pipeline stages (Parse → Extract → Store → Retrieve).
            Vary one stage at a time to compare frameworks, ontologies, and retrieval strategies.
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" onClick={() => setCreating((v) => !v)}>
            {creating ? "Close" : "New configuration"}
          </Button>
          <Button variant="outline" size="sm" onClick={() => void reload()} disabled={loading}>
            Refresh
          </Button>
        </div>
      </header>

      {creating && stages && (
        <section className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
          <h2 className="text-h5 text-foreground">New configuration</h2>
          <div className="flex gap-3">
            <label className="flex flex-1 flex-col gap-1 text-caption text-muted-foreground">
              Name
              <Input value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} placeholder="e.g. graph-vs-msgraphrag" />
            </label>
            <label className="flex flex-[2] flex-col gap-1 text-caption text-muted-foreground">
              Description
              <Input value={draft.description} onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))} />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Select label="Extractor" value={draft.extractor} options={pluginOpts(stages.extractors)} onChange={(v) => setDraft((d) => ({ ...d, extractor: v }))} />
            <Select label="Ontology" value={draft.ontology_version} options={stages.ontology_versions} onChange={(v) => setDraft((d) => ({ ...d, ontology_version: v }))} />
            <Select label="Graph store" value={draft.graph_store} options={pluginOpts(stages.graph_stores)} onChange={(v) => setDraft((d) => ({ ...d, graph_store: v }))} />
            <Select label="Retrieval" value={draft.retrieval_strategy} options={pluginOpts(stages.retrievers)} onChange={(v) => setDraft((d) => ({ ...d, retrieval_strategy: v }))} />
            <Select label="Provider" value={draft.provider} options={stages.providers} onChange={(v) => setDraft((d) => ({ ...d, provider: v }))} />
          </div>
          {errors.length > 0 && (
            <ul className="rounded-md border border-destructive/40 bg-destructive/10 p-2">
              {errors.map((e, i) => (
                <li key={i} className="text-caption text-destructive">{e}</li>
              ))}
            </ul>
          )}
          <div className="flex gap-2">
            <Button onClick={() => void submit()} disabled={busy}>
              {busy ? "Saving…" : "Create configuration"}
            </Button>
            <Button variant="ghost" onClick={() => setCreating(false)} disabled={busy}>Cancel</Button>
          </div>
        </section>
      )}

      <div className="flex flex-col gap-3">
        {configs.map((c) => (
          <div key={c.id} className="rounded-lg border border-border bg-card p-4">
            <div className="mb-2 flex items-center gap-2">
              <span className="text-p font-medium text-foreground">{c.name}</span>
              <span className="text-caption text-muted-foreground">v{c.version}</span>
              {c.is_builtin && <Badge variant="info">built-in</Badge>}
              <Badge variant="outline" className="font-mono">{c.content_hash.slice(0, 10)}</Badge>
            </div>
            {c.description ? <p className="mb-2 text-caption text-muted-foreground">{c.description}</p> : null}
            <div className="flex flex-wrap items-stretch gap-2">
              <StageCard label="Parse" value="parse" />
              <Arrow />
              <StageCard label="Extract" value={c.extractor} sub={ontologyName[c.ontology_version ?? ""] ?? c.ontology_version ?? undefined} />
              <Arrow />
              <StageCard label="Store" value={c.graph_store} />
              <Arrow />
              <StageCard label="Retrieve" value={c.retrieval_strategy} />
              <div className="self-center">
                <Badge variant="secondary">{c.provider}</Badge>
              </div>
            </div>
          </div>
        ))}
        {!loading && configs.length === 0 && (
          <p className="text-caption text-muted-foreground">No configurations yet.</p>
        )}
        {loading && <p className="text-caption text-muted-foreground">Loading…</p>}
      </div>
    </div>
  );
}
