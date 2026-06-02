"use client";

import { useEffect, useState } from "react";

import { ProviderSettingsSection } from "@/components/provider-settings-section";
import { WorkspaceResetSection } from "@/components/workspace-reset-section";
import {
  PIPELINE_DEFAULTS,
  pipelineSettingsPatchSchema,
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
  const [northLabel, setNorthLabel] = useState("North API");
  const [northSecret, setNorthSecret] = useState("");
  const [northUrlDraft, setNorthUrlDraft] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [northTestBusy, setNorthTestBusy] = useState(false);

  const [slackConnected, setSlackConnected] = useState(false);
  const [slackTeam, setSlackTeam] = useState<string | null>(null);
  const [slackToken, setSlackToken] = useState("");
  const [slackBusy, setSlackBusy] = useState(false);

  async function loadSlack() {
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/slack/connection`, {
        cache: "no-store",
      });
      const body = (await res.json().catch(() => ({}))) as {
        connected?: boolean;
        connection?: { slack_team_name?: string | null } | null;
      };
      setSlackConnected(Boolean(body.connected));
      setSlackTeam(body.connection?.slack_team_name ?? null);
    } catch {
      setSlackConnected(false);
    }
  }

  async function connectSlack(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    if (!slackToken.trim()) return;
    setSlackBusy(true);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/slack/connect-token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bot_token: slackToken.trim() }),
      });
      const body = (await res.json().catch(() => ({}))) as {
        connected?: boolean;
        connection?: { slack_team_name?: string | null } | null;
        error?: { message?: string };
        detail?: { error?: { message?: string } };
      };
      if (!res.ok || !body.connected) {
        setErr(body.error?.message ?? body.detail?.error?.message ?? "Slack connect failed");
        return;
      }
      setSlackToken("");
      setMsg(`Slack connected (${body.connection?.slack_team_name ?? "workspace"}).`);
      await loadSlack();
    } finally {
      setSlackBusy(false);
    }
  }

  async function disconnectSlack() {
    if (!confirm("Disconnect Slack and remove the stored bot token?")) return;
    setSlackBusy(true);
    setErr(null);
    try {
      await fetch(`/api/v1/workspaces/${workspaceId}/slack/connection`, { method: "DELETE" });
      setMsg("Slack disconnected.");
      await loadSlack();
    } finally {
      setSlackBusy(false);
    }
  }

  async function reload() {
    setSettingsLoading(true);
    try {
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
        setNorthUrlDraft(pJson.north_base_url ?? "");
      }
    } finally {
      setSettingsLoading(false);
    }
  }

  useEffect(() => {
    void reload();
    void loadSlack();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload on workspace change only
  }, [workspaceId]);

  const cohereKey = keys.find((k) => k.kind === "llm_cohere");
  const northKey = keys.find((k) => k.kind === "north_bearer");

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

  async function saveNorthUrl(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    setBusy(true);
    try {
      const trimmed = northUrlDraft.trim();
      const patch = { north_base_url: trimmed === "" ? "" : trimmed };
      const parsed = pipelineSettingsPatchSchema.safeParse(patch);
      if (!parsed.success) {
        setErr(parsed.error.flatten().fieldErrors.north_base_url?.join(", ") ?? "Invalid North URL");
        return;
      }
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/settings/pipeline`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed.data),
      });
      const body = (await res.json().catch(() => ({}))) as {
        error?: { message?: string };
      };
      if (!res.ok) {
        setErr(body.error?.message ?? `Save failed (${res.status})`);
        return;
      }
      setMsg("North API URL saved.");
      await reload();
    } finally {
      setBusy(false);
    }
  }

  async function saveNorthKey(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    setBusy(true);
    try {
      if (northKey) {
        const patchBody: { label: string; secret?: string } = { label: northLabel };
        if (northSecret.length >= 8) {
          patchBody.secret = northSecret;
        }
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/api-keys/${northKey.id}`,
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
        setNorthSecret("");
        setMsg(patchBody.secret ? "North token rotated." : "North token label updated.");
      } else {
        const res = await fetch(`/api/v1/workspaces/${workspaceId}/api-keys`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            kind: "north_bearer",
            label: northLabel,
            secret: northSecret,
          }),
        });
        const body = (await res.json().catch(() => ({}))) as {
          error?: { message?: string };
        };
        if (!res.ok) {
          setErr(body.error?.message ?? `Save failed (${res.status})`);
          return;
        }
        setNorthSecret("");
        setMsg("North bearer token saved. Secret is not shown again.");
      }
      await reload();
    } finally {
      setBusy(false);
    }
  }

  async function testNorth() {
    setErr(null);
    setMsg(null);
    setNorthTestBusy(true);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/providers/north/test`, {
        method: "POST",
      });
      const body = (await res.json()) as {
        ok?: boolean;
        agent_count?: number;
        error?: { message?: string };
      };
      if (!res.ok) {
        setErr(body.error?.message ?? `North test failed (${res.status})`);
        return;
      }
      if (body.ok) {
        setMsg(`North connectivity OK (${body.agent_count ?? 0} agents visible).`);
      } else {
        setErr(body.error?.message ?? "North test failed");
      }
    } finally {
      setNorthTestBusy(false);
    }
  }

  async function removeNorthKey() {
    if (!northKey) return;
    if (!confirm("Remove the stored North bearer token?")) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch(
        `/api/v1/workspaces/${workspaceId}/api-keys/${northKey.id}`,
        { method: "DELETE" },
      );
      if (!res.ok && res.status !== 204) {
        const body = (await res.json().catch(() => ({}))) as {
          error?: { message?: string };
        };
        setErr(body.error?.message ?? "Delete failed");
        return;
      }
      setMsg("North token removed.");
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
        <h1 className="text-h3 text-foreground">Settings</h1>
        <p className="mt-2 max-w-2xl text-p text-muted-foreground">
          Manage encrypted credentials and review pipeline defaults. API responses never include
          secrets (FR-30).
        </p>
      </header>

      {settingsLoading ? (
        <p className="text-caption text-muted-foreground" role="status">
          Loading workspace settings…
        </p>
      ) : null}

      <section
        className="rounded-lg border border-input bg-card p-5"
        aria-labelledby="north-integration-title"
      >
        <h2 id="north-integration-title" className="text-h5 text-foreground">
          North integration
        </h2>
        <p className="mt-2 text-caption text-muted-foreground">
          Configure the North Agents API for conversation import (see <span className="font-medium text-foreground">Agents</span>{" "}
          in the sidebar). Base URL lives in pipeline settings; bearer token is encrypted like other API keys and never
          returned on read. For <span className="font-mono text-muted-foreground">demo.north.cohere.com</span>, the pipeline
          adds <span className="font-mono text-muted-foreground">/api</span> when you save only the origin (so requests hit{" "}
          <span className="font-mono text-muted-foreground">…/api/v1/…</span>). Use a <span className="font-medium text-muted-foreground">North</span> API token for this host — a
          Cohere Command/Embed production key is different. If Test North reports a login redirect, rotate the token and
          try again.
        </p>
        <form className="mt-4 flex max-w-xl flex-col gap-3" onSubmit={saveNorthUrl}>
          <label className="flex flex-col gap-1 text-caption text-muted-foreground">
            North API base URL
            <input
              className="rounded-md border border-input bg-secondary px-3 py-2 font-mono text-p text-foreground"
              value={northUrlDraft}
              onChange={(ev) => setNorthUrlDraft(ev.target.value)}
              placeholder="https://demo.north.cohere.com/api"
              autoComplete="off"
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className="w-fit rounded-md bg-primary px-4 py-2 text-p font-medium text-[var(--bg-background)] hover:bg-primary/90 disabled:opacity-50"
          >
            {busy ? "Working…" : "Save North URL"}
          </button>
        </form>

        <form className="mt-8 flex max-w-xl flex-col gap-3" onSubmit={saveNorthKey}>
          <h3 className="text-p font-medium text-foreground">
            {northKey ? "Rotate North bearer token" : "Add North bearer token"}
          </h3>
          <label className="flex flex-col gap-1 text-caption text-muted-foreground">
            Label
            <input
              className="rounded-md border border-input bg-secondary px-3 py-2 text-p text-foreground"
              value={northLabel}
              onChange={(ev) => setNorthLabel(ev.target.value)}
              required
              maxLength={80}
            />
          </label>
          <label className="flex flex-col gap-1 text-caption text-muted-foreground">
            Bearer token
            <input
              type="password"
              autoComplete="off"
              className="rounded-md border border-input bg-secondary px-3 py-2 font-mono text-p text-foreground"
              value={northSecret}
              onChange={(ev) => setNorthSecret(ev.target.value)}
              required={!northKey}
              minLength={northKey ? undefined : 8}
              placeholder={northKey ? "Leave blank to keep current token" : "…"}
            />
          </label>
          <div className="flex flex-wrap gap-2 pt-2">
            <button
              type="submit"
              disabled={
                busy ||
                (!northKey && northSecret.length < 8) ||
                (northSecret.length > 0 && northSecret.length < 8)
              }
              className="rounded-md bg-primary px-4 py-2 text-p font-medium text-[var(--bg-background)] hover:bg-primary/90 disabled:opacity-50"
            >
              {busy ? "Working…" : northKey ? "Rotate token" : "Save token"}
            </button>
            <button
              type="button"
              disabled={busy || northTestBusy || !northKey}
              onClick={() => void testNorth()}
              className="rounded-md border border-input px-4 py-2 text-p text-muted-foreground hover:bg-secondary disabled:opacity-50"
            >
              {northTestBusy ? "Testing…" : "Test North"}
            </button>
            {northKey ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void removeNorthKey()}
                className="rounded-md border border-[color:var(--semantic-danger)] px-4 py-2 text-p text-[color:var(--semantic-danger)] hover:bg-secondary disabled:opacity-50"
              >
                Remove token
              </button>
            ) : null}
          </div>
        </form>
      </section>

      <section
        className="rounded-lg border border-input bg-card p-5"
        aria-labelledby="slack-integration-title"
      >
        <h2 id="slack-integration-title" className="text-h5 text-foreground">
          Slack integration
        </h2>
        <p className="mt-2 text-caption text-muted-foreground">
          Connect a Slack workspace to import channel conversations (see{" "}
          <span className="font-medium text-foreground">Slack</span> in the sidebar). Paste a{" "}
          <span className="font-mono text-muted-foreground">xoxb-…</span> bot token from your Slack
          app&apos;s OAuth &amp; Permissions page. The token is encrypted and never returned on
          read. The bot must be invited to each channel you want to import
          (<span className="font-mono text-muted-foreground">/invite @your-app</span>).
        </p>

        {slackConnected ? (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <span className="rounded-md border border-border bg-secondary/60 px-3 py-2 text-caption text-muted-foreground">
              Connected to{" "}
              <span className="font-medium text-foreground">{slackTeam ?? "Slack"}</span>
            </span>
            <button
              type="button"
              disabled={slackBusy}
              onClick={() => void disconnectSlack()}
              className="rounded-md border border-[color:var(--semantic-danger)] px-4 py-2 text-p text-[color:var(--semantic-danger)] hover:bg-secondary disabled:opacity-50"
            >
              {slackBusy ? "Working…" : "Disconnect Slack"}
            </button>
          </div>
        ) : (
          <form className="mt-4 flex max-w-xl flex-col gap-3" onSubmit={connectSlack}>
            <label className="flex flex-col gap-1 text-caption text-muted-foreground">
              Bot token (xoxb-…)
              <input
                type="password"
                autoComplete="off"
                className="rounded-md border border-input bg-secondary px-3 py-2 font-mono text-p text-foreground"
                value={slackToken}
                onChange={(ev) => setSlackToken(ev.target.value)}
                placeholder="xoxb-…"
              />
            </label>
            <button
              type="submit"
              disabled={slackBusy || !slackToken.trim()}
              className="w-fit rounded-md bg-primary px-4 py-2 text-p font-medium text-[var(--bg-background)] hover:bg-primary/90 disabled:opacity-50"
            >
              {slackBusy ? "Connecting…" : "Connect Slack"}
            </button>
          </form>
        )}
      </section>

      <section className="rounded-lg border border-input bg-card p-5" aria-labelledby="api-keys-title">
        <h2 id="api-keys-title" className="text-h5 text-foreground">
          API keys
        </h2>
        <p className="mt-2 text-caption text-muted-foreground">
          Cohere production key powers Command (via OpenAI-compat), Embed v3, and Rerank v3.
        </p>

        <ul className="mt-4 space-y-3">
          {keys.map((k) => (
            <li
              key={k.id}
              className="rounded-md border border-border bg-secondary/60 px-4 py-3 text-caption text-muted-foreground"
            >
              <span className="font-medium text-foreground">{k.label}</span>
              <span className="mx-2 text-muted-foreground">·</span>
              <span>{k.kind}</span>
              <span className="mx-2 text-muted-foreground">·</span>
              <span>last used: {k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "—"}</span>
            </li>
          ))}
          {keys.length === 0 ? (
            <li className="text-caption text-muted-foreground">No keys stored yet.</li>
          ) : null}
        </ul>

        <form className="mt-6 flex max-w-xl flex-col gap-3" onSubmit={saveKey}>
          <h3 className="text-p font-medium text-foreground">
            {cohereKey ? "Rotate Cohere key" : "Add Cohere key"}
          </h3>
          <label className="flex flex-col gap-1 text-caption text-muted-foreground">
            Label
            <input
              className="rounded-md border border-input bg-secondary px-3 py-2 text-p text-foreground"
              value={label}
              onChange={(ev) => setLabel(ev.target.value)}
              required
              maxLength={80}
            />
          </label>
          <label className="flex flex-col gap-1 text-caption text-muted-foreground">
            Secret
            <input
              type="password"
              autoComplete="off"
              className="rounded-md border border-input bg-secondary px-3 py-2 font-mono text-p text-foreground"
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
              className="rounded-md bg-primary px-4 py-2 text-p font-medium text-[var(--bg-background)] hover:bg-primary/90 disabled:opacity-50"
            >
              {busy ? "Working…" : cohereKey ? "Rotate key" : "Save key"}
            </button>
            <button
              type="button"
              disabled={busy || !cohereKey}
              onClick={() => void testCohere()}
              className="rounded-md border border-input px-4 py-2 text-p text-muted-foreground hover:bg-secondary disabled:opacity-50"
            >
              Test Cohere
            </button>
            {cohereKey ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void removeKey()}
                className="rounded-md border border-[color:var(--semantic-danger)] px-4 py-2 text-p text-[color:var(--semantic-danger)] hover:bg-secondary disabled:opacity-50"
              >
                Remove
              </button>
            ) : null}
          </div>
        </form>
      </section>

      <section
        className="rounded-lg border border-input bg-card p-5"
        aria-labelledby="pipeline-title"
      >
        <h2 id="pipeline-title" className="text-h5 text-foreground">
          Pipeline
        </h2>
        <p className="mt-2 text-caption text-muted-foreground">
          Provider:{" "}
          <span className="rounded bg-secondary px-2 py-0.5 text-muted-foreground opacity-60">
            Cohere (locked in P0)
          </span>
          . More providers ship in a later release (US-5.2). Defaults below match techstack — edit via
          API if needed; UI stays read-only for models this sprint.
        </p>
        <dl className="mt-4 grid grid-cols-1 gap-3 text-caption text-muted-foreground sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">Small model</dt>
            <dd className="font-mono text-foreground">{pipeline.small_model}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Large model</dt>
            <dd className="font-mono text-foreground">{pipeline.large_model}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Embed</dt>
            <dd className="font-mono text-foreground">{pipeline.embed_model}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Rerank</dt>
            <dd className="font-mono text-foreground">{pipeline.rerank_model}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Chunk size</dt>
            <dd className="font-mono text-foreground">{pipeline.chunk_size}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Max notes / document</dt>
            <dd className="font-mono text-foreground">{pipeline.max_notes_per_document}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">North base URL</dt>
            <dd className="font-mono text-foreground break-all">
              {pipeline.north_base_url ? pipeline.north_base_url : "—"}
            </dd>
          </div>
        </dl>
      </section>

      <ProviderSettingsSection workspaceId={workspaceId} />

      <WorkspaceResetSection workspaceId={workspaceId} />

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
