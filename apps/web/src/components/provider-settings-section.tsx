"use client";

import { useCallback, useEffect, useState } from "react";

type ProviderStatus = {
  id: string;
  label: string;
  supports_rerank: boolean;
  default_chat_model: string;
  default_embed_model: string;
  base_url_required: boolean;
  api_key_kind: string | null;
  configured?: boolean;
  base_url?: string;
  chat_model?: string;
  embed_model?: string;
  reason?: string;
};

type ApiKeyRow = { id: string; kind: string };

// Optional, OpenAI-compatible providers configured here. cohere_compat is the
// default and is managed by the Cohere API-key section above.
const OPTIONAL = new Set(["openai", "azure_openai"]);

export function ProviderSettingsSection({ workspaceId }: { workspaceId: string }) {
  const base = `/api/v1/workspaces/${encodeURIComponent(workspaceId)}`;
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [keysByKind, setKeysByKind] = useState<Record<string, string>>({});
  const [drafts, setDrafts] = useState<
    Record<string, { secret: string; base_url: string; chat_model: string; embed_model: string }>
  >({});
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const [pRes, kRes] = await Promise.all([
        fetch(`${base}/providers`, { cache: "no-store" }),
        fetch(`${base}/api-keys`, { cache: "no-store" }),
      ]);
      if (pRes.ok) {
        const body = (await pRes.json()) as { items?: ProviderStatus[] };
        setProviders(body.items ?? []);
      }
      if (kRes.ok) {
        const body = (await kRes.json()) as { items?: ApiKeyRow[] };
        const map: Record<string, string> = {};
        for (const k of body.items ?? []) map[k.kind] = k.id;
        setKeysByKind(map);
      }
    } catch {
      setErr("Failed to load providers");
    }
  }, [base]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const draftFor = (id: string) =>
    drafts[id] ?? { secret: "", base_url: "", chat_model: "", embed_model: "" };

  const setDraft = (id: string, patch: Partial<ReturnType<typeof draftFor>>) =>
    setDrafts((d) => ({ ...d, [id]: { ...draftFor(id), ...patch } }));

  const save = useCallback(
    async (p: ProviderStatus) => {
      setErr(null);
      setMsg(null);
      const d = draftFor(p.id);
      if (d.secret.length < 8) {
        setErr("API key must be at least 8 characters.");
        return;
      }
      if (p.base_url_required && !d.base_url.trim()) {
        setErr(`${p.label} requires a base URL.`);
        return;
      }
      const metadata: Record<string, string> = {};
      if (d.base_url.trim()) metadata.base_url = d.base_url.trim();
      if (d.chat_model.trim()) metadata.chat_model = d.chat_model.trim();
      if (d.embed_model.trim()) metadata.embed_model = d.embed_model.trim();
      setBusy(p.id);
      try {
        const res = await fetch(`${base}/api-keys`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            kind: p.api_key_kind,
            label: p.label,
            secret: d.secret,
            metadata,
          }),
        });
        const body = (await res.json().catch(() => ({}))) as { error?: { message?: string } };
        if (!res.ok) {
          setErr(
            body.error?.message ??
              (res.status === 409
                ? "A key already exists for this provider. Remove it first to replace."
                : `Save failed (${res.status})`),
          );
          return;
        }
        setDraft(p.id, { secret: "" });
        setMsg(`${p.label} key saved.`);
        await reload();
      } finally {
        setBusy(null);
      }
    },
    [base, drafts, reload],
  );

  const test = useCallback(
    async (p: ProviderStatus) => {
      setErr(null);
      setMsg(null);
      setBusy(p.id);
      try {
        const res = await fetch(`${base}/providers/${p.id}/test`, { method: "POST" });
        const body = (await res.json()) as {
          ok?: boolean;
          chat_model?: string;
          embed_model?: string;
          error?: { message?: string };
        };
        if (body.ok) {
          setMsg(`${p.label} OK (chat ${body.chat_model}, embed ${body.embed_model}).`);
        } else {
          setErr(body.error?.message ?? `${p.label} test failed`);
        }
      } finally {
        setBusy(null);
      }
    },
    [base],
  );

  const remove = useCallback(
    async (p: ProviderStatus) => {
      const id = p.api_key_kind ? keysByKind[p.api_key_kind] : undefined;
      if (!id) return;
      if (!confirm(`Remove the stored ${p.label} key?`)) return;
      setBusy(p.id);
      setErr(null);
      try {
        const res = await fetch(`${base}/api-keys/${id}`, { method: "DELETE" });
        if (!res.ok && res.status !== 204) {
          setErr("Delete failed");
          return;
        }
        setMsg(`${p.label} key removed.`);
        await reload();
      } finally {
        setBusy(null);
      }
    },
    [base, keysByKind, reload],
  );

  return (
    <section className="rounded-lg border border-input bg-card p-5" aria-labelledby="providers-title">
      <h2 id="providers-title" className="text-h5 text-foreground">
        LLM providers
      </h2>
      <p className="mt-2 max-w-2xl text-caption text-muted-foreground">
        Optional OpenAI-compatible providers used by individual pipeline configurations (e.g.
        Microsoft GraphRAG, ontology auto-tune). The built-in Graphiti pipeline always uses Cohere
        (configured in the API keys section above). Keys are encrypted and never returned on read.
      </p>

      <ul className="mt-4 space-y-4">
        {providers
          .filter((p) => OPTIONAL.has(p.id))
          .map((p) => {
            const d = draftFor(p.id);
            const hasKey = Boolean(p.api_key_kind && keysByKind[p.api_key_kind]);
            return (
              <li key={p.id} className="rounded-md border border-border bg-secondary/40 p-4">
                <div className="flex items-center gap-2">
                  <span className="text-p font-medium text-foreground">{p.label}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                      p.configured
                        ? "bg-[color:var(--semantic-success)]/15 text-[color:var(--semantic-success)]"
                        : "bg-secondary text-muted-foreground"
                    }`}
                  >
                    {p.configured ? "configured" : "not configured"}
                  </span>
                </div>
                <p className="mt-1 text-caption text-muted-foreground">
                  Defaults: chat <span className="font-mono">{p.default_chat_model}</span>, embed{" "}
                  <span className="font-mono">{p.default_embed_model}</span>. No reranker.
                </p>

                <div className="mt-3 grid max-w-2xl grid-cols-1 gap-2 sm:grid-cols-2">
                  <label className="flex flex-col gap-1 text-caption text-muted-foreground sm:col-span-2">
                    API key
                    <input
                      type="password"
                      autoComplete="off"
                      className="rounded-md border border-input bg-secondary px-3 py-2 font-mono text-p text-foreground"
                      value={d.secret}
                      onChange={(e) => setDraft(p.id, { secret: e.target.value })}
                      placeholder={hasKey ? "Stored — enter to replace" : "sk-…"}
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-caption text-muted-foreground sm:col-span-2">
                    Base URL {p.base_url_required ? "(required)" : "(optional)"}
                    <input
                      className="rounded-md border border-input bg-secondary px-3 py-2 font-mono text-p text-foreground"
                      value={d.base_url}
                      onChange={(e) => setDraft(p.id, { base_url: e.target.value })}
                      placeholder={p.base_url || "https://api.openai.com/v1"}
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-caption text-muted-foreground">
                    Chat model (optional)
                    <input
                      className="rounded-md border border-input bg-secondary px-3 py-2 font-mono text-p text-foreground"
                      value={d.chat_model}
                      onChange={(e) => setDraft(p.id, { chat_model: e.target.value })}
                      placeholder={p.default_chat_model}
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-caption text-muted-foreground">
                    Embed model (optional)
                    <input
                      className="rounded-md border border-input bg-secondary px-3 py-2 font-mono text-p text-foreground"
                      value={d.embed_model}
                      onChange={(e) => setDraft(p.id, { embed_model: e.target.value })}
                      placeholder={p.default_embed_model}
                    />
                  </label>
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={busy === p.id || d.secret.length < 8}
                    onClick={() => void save(p)}
                    className="rounded-md bg-primary px-4 py-2 text-p font-medium text-[var(--bg-background)] hover:bg-primary/90 disabled:opacity-50"
                  >
                    {busy === p.id ? "Working…" : hasKey ? "Replace key" : "Save key"}
                  </button>
                  <button
                    type="button"
                    disabled={busy === p.id || !hasKey}
                    onClick={() => void test(p)}
                    className="rounded-md border border-input px-4 py-2 text-p text-muted-foreground hover:bg-secondary disabled:opacity-50"
                  >
                    Test
                  </button>
                  {hasKey ? (
                    <button
                      type="button"
                      disabled={busy === p.id}
                      onClick={() => void remove(p)}
                      className="rounded-md border border-[color:var(--semantic-danger)] px-4 py-2 text-p text-[color:var(--semantic-danger)] hover:bg-secondary disabled:opacity-50"
                    >
                      Remove
                    </button>
                  ) : null}
                </div>
              </li>
            );
          })}
        {providers.filter((p) => OPTIONAL.has(p.id)).length === 0 ? (
          <li className="text-caption text-muted-foreground">No optional providers available.</li>
        ) : null}
      </ul>

      {msg ? (
        <p className="mt-3 text-caption text-[color:var(--semantic-success)]" role="status">
          {msg}
        </p>
      ) : null}
      {err ? (
        <p className="mt-3 text-caption text-[color:var(--semantic-danger)]" role="alert">
          {err}
        </p>
      ) : null}
    </section>
  );
}
