"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

type Props = {
  workspaceId: string;
  children: React.ReactNode;
};

export function FirstRunCohereGate({ workspaceId, children }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [label, setLabel] = useState("Cohere production");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/v1/workspaces/${workspaceId}/api-keys`);
        if (!res.ok) return;
        const data = (await res.json()) as { items?: { kind: string }[] };
        const has = data.items?.some((k) => k.kind === "llm_cohere");
        if (!cancelled && !has) setOpen(true);
      } catch {
        /* offline build / no DB */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/api-keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "llm_cohere",
          label,
          secret,
        }),
      });
      const body = (await res.json().catch(() => ({}))) as {
        error?: { message?: string };
      };
      if (!res.ok) {
        setError(body.error?.message ?? `Save failed (${res.status})`);
        return;
      }
      setSecret("");
      setOpen(false);
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {children}
      {open ? (
        <div
          className="fixed inset-0 z-[200] flex items-center justify-center bg-[var(--bg-canvas)]/85 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby="first-run-cohere-title"
        >
          <div className="w-full max-w-lg rounded-lg border border-border-strong bg-surface p-6 shadow-xl">
            <h2 id="first-run-cohere-title" className="text-title-2 text-primary">
              Connect Cohere
            </h2>
            <p className="mt-3 text-body text-secondary">
              zkast uses your Cohere production API key for Command (chat / extraction), Embed v3,
              and Rerank v3. The key is encrypted locally (AES-256-GCM); it is never sent back from
              the API after save. Only Cohere is contacted when you test or run graph jobs.
            </p>
            <p className="mt-2 text-caption text-muted">
              PDF upload and parsing do not require this key — choose Later if you only want to try
              ingestion first.
            </p>
            <form className="mt-6 flex flex-col gap-4" onSubmit={save}>
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
                API key
                <input
                  type="password"
                  autoComplete="off"
                  className="rounded-md border border-border-strong bg-surface-raised px-3 py-2 font-mono text-body text-primary"
                  value={secret}
                  onChange={(ev) => setSecret(ev.target.value)}
                  required
                  minLength={8}
                  placeholder="cohere-…"
                />
              </label>
              {error ? (
                <p className="text-caption text-[color:var(--semantic-danger)]" role="alert">
                  {error}
                </p>
              ) : null}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  className="rounded-md border border-border-strong px-4 py-2 text-body text-secondary hover:bg-surface-raised"
                  onClick={() => setOpen(false)}
                >
                  Later
                </button>
                <button
                  type="submit"
                  disabled={busy}
                  className="rounded-md bg-accent-primary px-4 py-2 text-body font-medium text-[var(--bg-canvas)] hover:bg-accent-primary-hover disabled:opacity-50"
                >
                  {busy ? "Saving…" : "Save encrypted key"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}
