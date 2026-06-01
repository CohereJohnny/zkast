"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useToast } from "@/components/feedback-provider";

type SyncState = {
  last_imported_at?: string | null;
  last_import_range?: string | null;
  last_import_created?: number | null;
  newest_message_at?: string | null;
  oldest_message_at?: string | null;
};

type Channel = {
  channel_id: string;
  name: string;
  is_private: boolean;
  is_member: boolean;
  num_members?: number | null;
  topic?: string | null;
  registered: boolean;
  source_id?: string | null;
  sync?: SyncState | null;
};

type Connection = {
  slack_team_name?: string | null;
  slack_team_id?: string | null;
} | null;

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
  const base = `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/slack`;

  const [connected, setConnected] = useState(false);
  const [connection, setConnection] = useState<Connection>(null);
  const [token, setToken] = useState("");
  const [connecting, setConnecting] = useState(false);

  const [channels, setChannels] = useState<Channel[]>([]);
  const [loadingChannels, setLoadingChannels] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [filter, setFilter] = useState("");
  const [membersOnly, setMembersOnly] = useState(true);
  const [ranges, setRanges] = useState<Record<string, string>>({});
  const [busyChannel, setBusyChannel] = useState<string | null>(null);

  const loadConnection = useCallback(async () => {
    try {
      const res = await fetch(`${base}/connection`, { cache: "no-store" });
      const body = (await res.json()) as { connected?: boolean; connection?: Connection };
      setConnected(Boolean(body.connected));
      setConnection(body.connection ?? null);
      return Boolean(body.connected);
    } catch {
      setConnected(false);
      return false;
    }
  }, [base]);

  const loadChannels = useCallback(async () => {
    setLoadingChannels(true);
    setError(null);
    try {
      const res = await fetch(`${base}/channels`, { cache: "no-store" });
      const body = (await res.json()) as { items?: Channel[]; error?: { message?: string } };
      if (!res.ok) {
        setError(body.error?.message ?? "Failed to load channels");
        return;
      }
      setChannels(body.items ?? []);
    } catch {
      setError("Failed to load channels");
    } finally {
      setLoadingChannels(false);
    }
  }, [base]);

  useEffect(() => {
    void (async () => {
      const ok = await loadConnection();
      if (ok) void loadChannels();
    })();
  }, [loadConnection, loadChannels]);

  const connectToken = useCallback(async () => {
    if (!token.trim()) return;
    setConnecting(true);
    try {
      const res = await fetch(`${base}/connect-token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bot_token: token.trim() }),
      });
      const body = (await res.json()) as {
        connected?: boolean;
        connection?: Connection;
        error?: { message?: string };
        detail?: { error?: { message?: string } };
      };
      if (!res.ok || !body.connected) {
        toast({
          variant: "error",
          message: body.error?.message ?? body.detail?.error?.message ?? "Connect failed",
        });
        return;
      }
      setToken("");
      toast({ variant: "success", message: `Connected to ${body.connection?.slack_team_name ?? "Slack"}` });
      setConnected(true);
      setConnection(body.connection ?? null);
      void loadChannels();
    } finally {
      setConnecting(false);
    }
  }, [base, token, toast, loadChannels]);

  const disconnect = useCallback(async () => {
    await fetch(`${base}/connection`, { method: "DELETE" });
    setConnected(false);
    setConnection(null);
    setChannels([]);
    toast({ variant: "success", message: "Slack disconnected" });
  }, [base, toast]);

  const importChannel = useCallback(
    async (ch: Channel) => {
      setBusyChannel(ch.channel_id);
      try {
        // Register the channel as a memory source if needed.
        let sourceId = ch.source_id ?? null;
        if (!sourceId) {
          const regRes = await fetch(`${base}/channels/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ channel_id: ch.channel_id, channel_name: ch.name }),
          });
          const regBody = (await regRes.json()) as {
            source?: { id?: string };
            error?: { message?: string };
          };
          if (!regRes.ok || !regBody.source?.id) {
            toast({ variant: "error", message: regBody.error?.message ?? "Register failed" });
            return;
          }
          sourceId = regBody.source.id;
        }

        const range = ranges[ch.channel_id] ?? "last_90_days";
        const res = await fetch(`${base}/channels/${encodeURIComponent(sourceId)}/import`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ range }),
        });
        const body = (await res.json()) as {
          units?: number;
          created?: number;
          skipped?: number;
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
        toast({
          variant: "success",
          message: `#${ch.name}: ${body.created ?? 0} imported, ${body.skipped ?? 0} already present`,
        });
        void loadChannels();
      } catch {
        toast({ variant: "error", message: "Import request failed" });
      } finally {
        setBusyChannel(null);
      }
    },
    [base, ranges, toast, loadChannels],
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
          Connect a Slack workspace, then import channel conversations into the
          knowledge graph. Threads and message sessions become agent-scoped memory.
        </p>
      </header>

      {/* Connection */}
      <section className="rounded-lg border border-border bg-card/80 p-4">
        <h2 className="text-h5 text-foreground">Connection</h2>
        {connected ? (
          <div className="mt-2 flex items-center justify-between gap-4">
            <p className="text-p text-muted-foreground">
              Connected to{" "}
              <span className="text-foreground">{connection?.slack_team_name ?? "Slack"}</span>
            </p>
            <button
              type="button"
              onClick={() => void disconnect()}
              className="rounded-md border border-input px-3 py-1.5 text-caption text-muted-foreground hover:bg-secondary"
            >
              Disconnect
            </button>
          </div>
        ) : (
          <div className="mt-2 flex flex-col gap-2">
            <p className="text-caption text-muted-foreground">
              Paste a Slack bot token (<code>xoxb-…</code>) from your Slack app&apos;s
              OAuth &amp; Permissions page. The bot must be invited to channels you want to import.
            </p>
            <div className="flex gap-2">
              <input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="xoxb-…"
                className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-p text-foreground"
              />
              <button
                type="button"
                disabled={connecting || !token.trim()}
                onClick={() => void connectToken()}
                className="rounded-md bg-primary px-3 py-1.5 text-caption text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                {connecting ? "Connecting…" : "Connect"}
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Channels */}
      {connected ? (
        <section className="rounded-lg border border-border bg-card/80 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-h5 text-foreground">Channels</h2>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1.5 text-caption text-muted-foreground">
                <input
                  type="checkbox"
                  checked={membersOnly}
                  onChange={(e) => setMembersOnly(e.target.checked)}
                />
                Only channels the bot is in
              </label>
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter…"
                className="rounded-md border border-input bg-background px-2 py-1 text-caption text-foreground"
              />
              <button
                type="button"
                onClick={() => void loadChannels()}
                className="rounded-md border border-input px-3 py-1 text-caption text-muted-foreground hover:bg-secondary"
              >
                Refresh
              </button>
            </div>
          </div>

          {error ? (
            <p className="mt-2 text-caption text-red-400" role="alert">
              {error}
            </p>
          ) : null}

          {loadingChannels && channels.length === 0 ? (
            <p className="mt-3 text-caption text-muted-foreground">Loading channels…</p>
          ) : (
            <ul className="mt-3 divide-y divide-border">
              {visibleChannels.map((ch) => {
                const busy = busyChannel === ch.channel_id;
                const range = ranges[ch.channel_id] ?? "last_90_days";
                return (
                  <li key={ch.channel_id} className="flex flex-wrap items-center gap-3 py-3">
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
                            invite @zkast
                          </span>
                        ) : null}
                        {ch.registered ? (
                          <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] uppercase text-muted-foreground">
                            registered
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-0.5 text-caption text-muted-foreground">
                        {ch.num_members ?? 0} members
                        {ch.sync?.last_imported_at ? (
                          <>
                            {" · "}
                            imported {ch.sync.last_import_created ?? 0} on{" "}
                            {fmtDate(ch.sync.last_imported_at)} · covers{" "}
                            {fmtDate(ch.sync.oldest_message_at)} → {fmtDate(ch.sync.newest_message_at)}
                          </>
                        ) : null}
                      </p>
                    </div>
                    <select
                      value={range}
                      disabled={!ch.is_member || busy}
                      onChange={(e) =>
                        setRanges((r) => ({ ...r, [ch.channel_id]: e.target.value }))
                      }
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
                      disabled={!ch.is_member || busy}
                      onClick={() => void importChannel(ch)}
                      title={ch.is_member ? "" : "Invite @zkast to this channel in Slack first"}
                      className="rounded-md bg-primary px-3 py-1.5 text-caption text-primary-foreground hover:opacity-90 disabled:opacity-50"
                    >
                      {busy ? "Importing…" : "Import"}
                    </button>
                  </li>
                );
              })}
              {visibleChannels.length === 0 ? (
                <li className="py-3 text-caption text-muted-foreground">
                  No channels match. {membersOnly ? "Try unchecking the members-only filter." : ""}
                </li>
              ) : null}
            </ul>
          )}
        </section>
      ) : null}
    </div>
  );
}
