"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useToast } from "@/components/feedback-provider";
import { useJobEvents } from "@/lib/job-events";

type SyncState = {
  last_imported_at?: string | null;
  last_import_range?: string | null;
  last_import_created?: number | null;
  newest_message_at?: string | null;
  oldest_message_at?: string | null;
};

type SlackSource = {
  source_id: string;
  channel_id: string;
  name: string;
  sync?: SyncState | null;
};

type Channel = {
  channel_id: string;
  name: string;
  is_private: boolean;
  is_member: boolean;
  num_members?: number | null;
  registered: boolean;
  source_id?: string | null;
};

const RANGE_OPTIONS: { value: string; label: string }[] = [
  { value: "last_90_days", label: "Last 90 days" },
  { value: "last_180_days", label: "Last 180 days" },
  { value: "last_365_days", label: "Last year" },
  { value: "all", label: "All history" },
  { value: "since_last", label: "Since last import" },
];

function fmtDate(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
}

export function SlackPageClient({ workspaceId }: { workspaceId: string }) {
  const toast = useToast();
  const { registerActiveJob, requestOpenLogConsole } = useJobEvents();
  const base = `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/slack`;

  const [connected, setConnected] = useState(false);
  const [team, setTeam] = useState<string | null>(null);

  const [sources, setSources] = useState<SlackSource[]>([]);
  const [ranges, setRanges] = useState<Record<string, string>>({});
  const [busySource, setBusySource] = useState<string | null>(null);

  const [addId, setAddId] = useState("");
  const [addName, setAddName] = useState("");
  const [adding, setAdding] = useState(false);
  const [dreaming, setDreaming] = useState<string | null>(null);

  const [showBrowse, setShowBrowse] = useState(false);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loadingChannels, setLoadingChannels] = useState(false);
  const [filter, setFilter] = useState("");
  const [membersOnly, setMembersOnly] = useState(true);

  const loadConnection = useCallback(async () => {
    try {
      const res = await fetch(`${base}/connection`, { cache: "no-store" });
      const body = (await res.json()) as {
        connected?: boolean;
        connection?: { slack_team_name?: string | null } | null;
      };
      setConnected(Boolean(body.connected));
      setTeam(body.connection?.slack_team_name ?? null);
      return Boolean(body.connected);
    } catch {
      setConnected(false);
      return false;
    }
  }, [base]);

  const loadSources = useCallback(async () => {
    try {
      const res = await fetch(`${base}/sources`, { cache: "no-store" });
      const body = (await res.json()) as { items?: SlackSource[] };
      setSources(body.items ?? []);
    } catch {
      /* non-fatal */
    }
  }, [base]);

  const loadChannels = useCallback(
    async (refresh = false) => {
      setLoadingChannels(true);
      try {
        const res = await fetch(`${base}/channels${refresh ? "?refresh=true" : ""}`, {
          cache: "no-store",
        });
        const body = (await res.json()) as { items?: Channel[]; error?: { message?: string } };
        if (!res.ok) {
          toast({ variant: "error", message: body.error?.message ?? "Failed to load channels" });
          return;
        }
        setChannels(body.items ?? []);
      } catch {
        toast({ variant: "error", message: "Failed to load channels" });
      } finally {
        setLoadingChannels(false);
      }
    },
    [base, toast],
  );

  useEffect(() => {
    void (async () => {
      const ok = await loadConnection();
      if (ok) void loadSources();
    })();
  }, [loadConnection, loadSources]);

  const registerChannel = useCallback(
    async (channelId: string, name: string): Promise<string | null> => {
      const res = await fetch(`${base}/channels/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel_id: channelId.trim(), channel_name: name.trim() || channelId.trim() }),
      });
      const body = (await res.json()) as { source?: { id?: string }; error?: { message?: string } };
      if (!res.ok || !body.source?.id) {
        toast({ variant: "error", message: body.error?.message ?? "Register failed" });
        return null;
      }
      return body.source.id;
    },
    [base, toast],
  );

  const runImport = useCallback(
    async (sourceId: string, channelName: string, range: string) => {
      setBusySource(sourceId);
      try {
        const res = await fetch(`${base}/channels/${encodeURIComponent(sourceId)}/import`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ range }),
        });
        const body = (await res.json()) as {
          created?: number;
          skipped?: number;
          documents?: { job_id: string; document_id: string }[];
          error?: { message?: string };
          detail?: { error?: { message?: string } };
        };
        if (!res.ok) {
          toast({
            variant: "error",
            message: body.error?.message ?? body.detail?.error?.message ?? "Import failed",
          });
          return;
        }
        // Stream the resulting pipeline jobs into the docked log console.
        (body.documents ?? []).slice(0, 12).forEach((d) => {
          registerActiveJob(d.job_id, workspaceId, d.document_id, "document_parse");
        });
        if ((body.documents ?? []).length > 0) requestOpenLogConsole();
        toast({
          variant: "success",
          message: `#${channelName}: ${body.created ?? 0} imported, ${body.skipped ?? 0} already present`,
        });
        void loadSources();
      } catch {
        toast({ variant: "error", message: "Import request failed" });
      } finally {
        setBusySource(null);
      }
    },
    [base, workspaceId, registerActiveJob, requestOpenLogConsole, toast, loadSources],
  );

  const dreamChannel = useCallback(
    async (sourceId: string, name: string) => {
      setDreaming(sourceId);
      try {
        const res = await fetch(
          `/api/v1/workspaces/${workspaceId}/north/agents/${encodeURIComponent(sourceId)}/dream`,
          { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" },
        );
        const body = (await res.json().catch(() => ({}))) as {
          job_id?: string;
          error?: { message?: string };
        };
        if (!res.ok) {
          toast({ variant: "error", message: body.error?.message ?? "Dream failed to start" });
          return;
        }
        if (body.job_id) {
          registerActiveJob(body.job_id, workspaceId, null, "dreaming");
          requestOpenLogConsole();
        }
        toast({ variant: "success", message: `Dreaming started for #${name}` });
      } catch {
        toast({ variant: "error", message: "Dream request failed" });
      } finally {
        setDreaming(null);
      }
    },
    [workspaceId, registerActiveJob, requestOpenLogConsole, toast],
  );

  const addByIdHandler = useCallback(async () => {
    if (!addId.trim()) return;
    setAdding(true);
    try {
      const sourceId = await registerChannel(addId, addName);
      if (sourceId) {
        toast({ variant: "success", message: `Channel registered` });
        setAddId("");
        setAddName("");
        await loadSources();
      }
    } finally {
      setAdding(false);
    }
  }, [addId, addName, registerChannel, toast, loadSources]);

  const importBrowseChannel = useCallback(
    async (ch: Channel) => {
      let sourceId = ch.source_id ?? null;
      if (!sourceId) {
        sourceId = await registerChannel(ch.channel_id, ch.name);
        if (!sourceId) return;
        await loadSources();
      }
      const range = ranges[ch.channel_id] ?? "last_90_days";
      await runImport(sourceId, ch.name, range);
    },
    [registerChannel, loadSources, ranges, runImport],
  );

  const visibleChannels = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return channels
      .filter((c) => (membersOnly ? c.is_member : true))
      .filter((c) => (q ? (c.name ?? "").toLowerCase().includes(q) : true))
      .sort((a, b) => (a.name ?? "").localeCompare(b.name ?? ""));
  }, [channels, filter, membersOnly]);

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-h3 text-foreground">Slack</h1>
        <p className="mt-1 text-caption text-muted-foreground">
          Import Slack channel conversations into the knowledge graph. Threads and message
          sessions become agent-scoped memory. Live import progress streams in the pipeline log below.
        </p>
      </header>

      {!connected ? (
        <section className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4">
          <p className="text-p text-foreground">Slack is not connected.</p>
          <p className="mt-1 text-caption text-muted-foreground">
            Connect a Slack bot token in{" "}
            <Link href="/settings" className="font-medium text-foreground underline">
              Settings → Slack integration
            </Link>
            , then return here to import channels.
          </p>
        </section>
      ) : (
        <>
          <section className="rounded-lg border border-border bg-card/80 p-4">
            <div className="flex items-center justify-between gap-2">
              <p className="text-caption text-muted-foreground">
                Connected to <span className="text-foreground">{team ?? "Slack"}</span>
              </p>
              <Link
                href="/settings"
                className="text-caption text-muted-foreground underline hover:text-foreground"
              >
                Manage connection
              </Link>
            </div>

            {/* Explicit add-by-ID — fast path that avoids the full channel listing. */}
            <div className="mt-3 border-t border-border pt-3">
              <h3 className="text-caption font-semibold uppercase tracking-wider text-muted-foreground">
                Add a channel
              </h3>
              <p className="mt-1 text-caption text-muted-foreground">
                Paste a Slack channel ID (e.g. <span className="font-mono">C0A1JVCJL2D</span>) to
                register it directly. Invite the bot to the channel first.
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <input
                  value={addId}
                  onChange={(e) => setAddId(e.target.value)}
                  placeholder="Channel ID (C…)"
                  className="rounded-md border border-input bg-background px-3 py-1.5 font-mono text-caption text-foreground"
                />
                <input
                  value={addName}
                  onChange={(e) => setAddName(e.target.value)}
                  placeholder="Display name (optional)"
                  className="rounded-md border border-input bg-background px-3 py-1.5 text-caption text-foreground"
                />
                <button
                  type="button"
                  disabled={adding || !addId.trim()}
                  onClick={() => void addByIdHandler()}
                  className="rounded-md border border-input px-3 py-1.5 text-caption text-muted-foreground hover:bg-secondary disabled:opacity-50"
                >
                  {adding ? "Adding…" : "Add channel"}
                </button>
              </div>
            </div>
          </section>

          {/* Registered channels — fast, Postgres-only. */}
          <section className="rounded-lg border border-border bg-card/80 p-4">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-h5 text-foreground">Your channels</h2>
              <button
                type="button"
                onClick={() => void loadSources()}
                className="rounded-md border border-input px-3 py-1 text-caption text-muted-foreground hover:bg-secondary"
              >
                Refresh
              </button>
            </div>
            {sources.length === 0 ? (
              <p className="mt-3 text-caption text-muted-foreground">
                No channels registered yet. Add one above by ID, or browse all channels below.
              </p>
            ) : (
              <ul className="mt-3 divide-y divide-border">
                {sources.map((s) => {
                  const busy = busySource === s.source_id;
                  const range = ranges[s.channel_id] ?? "last_90_days";
                  return (
                    <li key={s.source_id} className="flex flex-wrap items-center gap-3 py-3">
                      <div className="min-w-0 flex-1">
                        <span className="truncate text-p text-foreground">#{s.name}</span>
                        <p className="mt-0.5 text-caption text-muted-foreground">
                          {s.sync?.last_imported_at ? (
                            <>
                              imported {s.sync.last_import_created ?? 0} on{" "}
                              {fmtDate(s.sync.last_imported_at)} · covers{" "}
                              {fmtDate(s.sync.oldest_message_at)} → {fmtDate(s.sync.newest_message_at)}
                            </>
                          ) : (
                            "not imported yet"
                          )}
                        </p>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-caption">
                          <Link
                            href={`/notes?agentId=${encodeURIComponent(s.source_id)}`}
                            className="text-link hover:underline"
                          >
                            Notes
                          </Link>
                          <Link
                            href={`/graph?agent_id=${encodeURIComponent(s.source_id)}`}
                            className="text-link hover:underline"
                          >
                            Graph
                          </Link>
                          <Link
                            href={`/chat?agent_id=${encodeURIComponent(s.source_id)}`}
                            className="text-link hover:underline"
                          >
                            Chat
                          </Link>
                          <button
                            type="button"
                            disabled={dreaming === s.source_id}
                            onClick={() => void dreamChannel(s.source_id, s.name)}
                            className="text-link hover:underline disabled:opacity-50"
                          >
                            {dreaming === s.source_id ? "Dreaming…" : "Dream"}
                          </button>
                        </div>
                      </div>
                      <select
                        value={range}
                        disabled={busy}
                        onChange={(e) => setRanges((r) => ({ ...r, [s.channel_id]: e.target.value }))}
                        className="rounded-md border border-input bg-background px-2 py-1 text-caption text-foreground disabled:opacity-50"
                      >
                        {RANGE_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void runImport(s.source_id, s.name, range)}
                        className="rounded-md bg-primary px-3 py-1.5 text-caption text-primary-foreground hover:opacity-90 disabled:opacity-50"
                      >
                        {busy ? "Importing…" : "Import"}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {/* Browse all channels — slow (rate-limited), cached server-side. */}
          <section className="rounded-lg border border-border bg-card/80 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-h5 text-foreground">Browse all channels</h2>
              {showBrowse ? (
                <div className="flex items-center gap-2">
                  <label className="flex items-center gap-1.5 text-caption text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={membersOnly}
                      onChange={(e) => setMembersOnly(e.target.checked)}
                    />
                    Bot is in
                  </label>
                  <input
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder="Filter…"
                    className="rounded-md border border-input bg-background px-2 py-1 text-caption text-foreground"
                  />
                  <button
                    type="button"
                    onClick={() => void loadChannels(true)}
                    className="rounded-md border border-input px-3 py-1 text-caption text-muted-foreground hover:bg-secondary"
                  >
                    Refresh
                  </button>
                </div>
              ) : null}
            </div>

            {!showBrowse ? (
              <button
                type="button"
                onClick={() => {
                  setShowBrowse(true);
                  void loadChannels(false);
                }}
                className="mt-3 rounded-md border border-input px-3 py-1.5 text-caption text-muted-foreground hover:bg-secondary"
              >
                Load all channels
              </button>
            ) : loadingChannels && channels.length === 0 ? (
              <p className="mt-3 text-caption text-muted-foreground">
                Loading channels… (large workspaces can take a moment; cached for 5 min)
              </p>
            ) : (
              <ul className="mt-3 max-h-[420px] divide-y divide-border overflow-auto">
                {visibleChannels.map((ch) => {
                  const range = ranges[ch.channel_id] ?? "last_90_days";
                  return (
                    <li key={ch.channel_id} className="flex flex-wrap items-center gap-3 py-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-p text-foreground">#{ch.name}</span>
                          {ch.is_private ? (
                            <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
                              private
                            </span>
                          ) : null}
                          {!ch.is_member ? (
                            <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] uppercase text-amber-500">
                              invite bot
                            </span>
                          ) : null}
                          {ch.registered ? (
                            <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
                              registered
                            </span>
                          ) : null}
                        </div>
                        <p className="text-caption text-muted-foreground">{ch.num_members ?? 0} members</p>
                      </div>
                      <select
                        value={range}
                        disabled={!ch.is_member}
                        onChange={(e) => setRanges((r) => ({ ...r, [ch.channel_id]: e.target.value }))}
                        className="rounded-md border border-input bg-background px-2 py-1 text-caption text-foreground disabled:opacity-50"
                      >
                        {RANGE_OPTIONS.map((o) => (
                          <option key={o.value} value={o.value}>
                            {o.label}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        disabled={!ch.is_member || busySource !== null}
                        onClick={() => void importBrowseChannel(ch)}
                        title={ch.is_member ? "" : "Invite the bot to this channel in Slack first"}
                        className="rounded-md bg-primary px-3 py-1.5 text-caption text-primary-foreground hover:opacity-90 disabled:opacity-50"
                      >
                        Import
                      </button>
                    </li>
                  );
                })}
                {visibleChannels.length === 0 ? (
                  <li className="py-3 text-caption text-muted-foreground">No channels match.</li>
                ) : null}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
