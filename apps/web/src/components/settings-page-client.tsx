"use client";

import { useEffect, useState } from "react";

import {
  PIPELINE_DEFAULTS,
  pipelineSettingsSchema,
  type PipelineSettings,
} from "@/lib/pipeline-settings";

type ApiKeyRow = {
  id: string;
  kind: string;
  label: string;
  metadata: unknown;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
};

export function SettingsPageClient({ workspaceId }: { workspaceId: string }) {
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [pipeline, setPipeline] = useState<PipelineSettings>(() =>
    pipelineSettingsSchema.parse({ ...PIPELINE_DEFAULTS }),
  );
  const [label, setLabel] = useState("Cohere production");
  const [secret, setSecret] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function reload() {
    const [kRes, pRes] = await Promise.all([
      fetch(`/api/v1/workspaces/${workspaceId}/api-keys`),
      fetch(`/api/v1/workspaces/${workspaceId}/settings/pipeline`),
    ]);
    if (kRes.ok) {
      const kJson = (await kRes.json()) as { items: ApiKeyRow[] };
      setKeys(kJson.items ?? []);
    }
    if (pRes.ok) {
      const pJson = (await pRes.json()) as PipelineSettings;
      setPipeline(pJson);
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload on workspace change only
  }, [workspaceId]);

  const cohereKey = keys.find((k) => k.kind === "llm_cohere");

  async function saveKey(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    setBusy(true);
    try {
      if (cohereKey) {
        const patchBody: { label: string; secret?: string } = { label };
        if (secret.length >= 8) {
          patchBody.secret = secret;
        }
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/api-keys/${cohereKey.id}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(patchBody),
          },
        );
        const body = (await res.json().catch(() => ({}))) as {
          error?: { message?: string };
        };
        if (!res.ok) {
          setErr(body.error?.message ?? `Update failed (${res.status})`);
          return;
        }
        setSecret("");
        setMsg(patchBody.secret ? "Key rotated. Secret is not shown again." : "Label updated.");
      } else {
        const res = await fetch(`/api/v1/workspaces/${workspaceId}/api-keys`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "llm_cohere", label, secret }),
        });
        const body = (await res.json().catch(() => ({}))) as {
          error?: { message?: string };
        };
        if (!res.ok) {
          setErr(body.error?.message ?? `Save failed (${res.status})`);
          return;
        }
        setSecret("");
        setMsg("Key saved. Secret is not shown again.");
      }
      await reload();
    } finally {
      setBusy(false);
    }
  }

  async function testCohere() {
    setErr(null);
    setMsg(null);
    setBusy(true);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/providers/cohere/test`,
        { method: "POST" },
      );
      const body = (await res.json()) as { ok?: boolean; error?: { message?: string } };
      if (body.ok) {
        setMsg("Cohere connectivity OK (chat + embed + rerank).");
      } else {
        setErr(body.error?.message ?? "Cohere test failed");
      }
    } finally {
      setBusy(false);
    }
  }

  async function removeKey() {
    if (!cohereKey) return;
    if (!confirm("Remove the stored Cohere API key?")) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/api-keys/${cohereKey.id}`,
        { method: "DELETE" },
      );
      if (!res.ok && res.status !== 204) {
        const body = (await res.json().catch(() => ({}))) as {
          error?: { message?: string };
        };
        setErr(body.error?.message ?? "Delete failed");
        return;
      }
      setMsg("Key removed.");
      await reload();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-8 p-6">
      <header>
        <h1 className="text-title-1 text-primary">Settings</h1>
        <p className="mt-2 max-w-2xl text-body text-secondary">
          Manage encrypted credentials and review pipeline defaults. API responses never include
          secrets (FR-30).
        </p>
      </header>

      <section className="rounded-lg border border-border-strong bg-surface p-5" aria-labelledby="api-keys-title">
        <h2 id="api-keys-title" className="text-title-3 text-primary">
          API keys
        </h2>
        <p className="mt-2 text-caption text-muted">
          Cohere production key powers Command (via OpenAI-compat), Embed v3, and Rerank v3.
        </p>

        <ul className="mt-4 space-y-3">
          {keys.map((k) => (
            <li
              key={k.id}
              className="rounded-md border border-border-subtle bg-surface-raised/60 px-4 py-3 text-caption text-secondary"
            >
              <span className="font-medium text-primary">{k.label}</span>
              <span className="mx-2 text-muted">·</span>
              <span>{k.kind}</span>
              <span className="mx-2 text-muted">·</span>
              <span>last used: {k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "—"}</span>
            </li>
          ))}
          {keys.length === 0 ? (
            <li className="text-caption text-muted">No keys stored yet.</li>
          ) : null}
        </ul>

        <form className="mt-6 flex max-w-xl flex-col gap-3" onSubmit={saveKey}>
          <h3 className="text-body font-medium text-primary">
            {cohereKey ? "Rotate Cohere key" : "Add Cohere key"}
          </h3>
          <label className="flex flex-col gap-1 text-caption text-secondary">
            Label
            <input
              className="rounded-md border border-border-strong bg-surface-raised px-3 py-2 text-body text-primary"
              value={label}
              onChange={(ev) => setLabel(ev.target.value)}
              required
              maxLength={80}
            />
          </label>
          <label className="flex flex-col gap-1 text-caption text-secondary">
            Secret
            <input
              type="password"
              autoComplete="off"
              className="rounded-md border border-border-strong bg-surface-raised px-3 py-2 font-mono text-body text-primary"
              value={secret}
              onChange={(ev) => setSecret(ev.target.value)}
              required={!cohereKey}
              minLength={cohereKey ? undefined : 8}
              placeholder={cohereKey ? "Leave blank to keep current secret" : "cohere-…"}
            />
          </label>
          <div className="flex flex-wrap gap-2 pt-2">
            <button
              type="submit"
              disabled={
                busy ||
                (!cohereKey && secret.length < 8) ||
                (secret.length > 0 && secret.length < 8)
              }
              className="rounded-md bg-accent-primary px-4 py-2 text-body font-medium text-[var(--bg-canvas)] hover:bg-accent-primary-hover disabled:opacity-50"
            >
              {busy ? "Working…" : cohereKey ? "Rotate key" : "Save key"}
            </button>
            <button
              type="button"
              disabled={busy || !cohereKey}
              onClick={() => void testCohere()}
              className="rounded-md border border-border-strong px-4 py-2 text-body text-secondary hover:bg-surface-raised disabled:opacity-50"
            >
              Test Cohere
            </button>
            {cohereKey ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void removeKey()}
                className="rounded-md border border-[color:var(--semantic-danger)] px-4 py-2 text-body text-[color:var(--semantic-danger)] hover:bg-surface-raised disabled:opacity-50"
              >
                Remove
              </button>
            ) : null}
          </div>
        </form>
      </section>

      <section
        className="rounded-lg border border-border-strong bg-surface p-5"
        aria-labelledby="pipeline-title"
      >
        <h2 id="pipeline-title" className="text-title-3 text-primary">
          Pipeline
        </h2>
        <p className="mt-2 text-caption text-muted">
          Provider:{" "}
          <span className="rounded bg-surface-raised px-2 py-0.5 text-secondary opacity-60">
            Cohere (locked in P0)
          </span>
          . More providers ship in a later release (US-5.2). Defaults below match techstack — edit via
          API if needed; UI stays read-only for models this sprint.
        </p>
        <dl className="mt-4 grid grid-cols-1 gap-3 text-caption text-secondary sm:grid-cols-2">
          <div>
            <dt className="text-muted">Small model</dt>
            <dd className="font-mono text-primary">{pipeline.small_model}</dd>
          </div>
          <div>
            <dt className="text-muted">Large model</dt>
            <dd className="font-mono text-primary">{pipeline.large_model}</dd>
          </div>
          <div>
            <dt className="text-muted">Embed</dt>
            <dd className="font-mono text-primary">{pipeline.embed_model}</dd>
          </div>
          <div>
            <dt className="text-muted">Rerank</dt>
            <dd className="font-mono text-primary">{pipeline.rerank_model}</dd>
          </div>
          <div>
            <dt className="text-muted">Chunk size</dt>
            <dd className="font-mono text-primary">{pipeline.chunk_size}</dd>
          </div>
          <div>
            <dt className="text-muted">Max notes / document</dt>
            <dd className="font-mono text-primary">{pipeline.max_notes_per_document}</dd>
          </div>
        </dl>
      </section>

      {msg ? (
        <p className="text-caption text-[color:var(--semantic-success)]" role="status">
          {msg}
        </p>
      ) : null}
      {err ? (
        <p className="text-caption text-[color:var(--semantic-danger)]" role="alert">
          {err}
        </p>
      ) : null}
    </div>
  );
}
