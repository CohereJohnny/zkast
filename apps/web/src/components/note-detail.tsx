"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useConfirm, usePrompt, useToast } from "@/components/feedback-provider";
import { NoteMergeDialog } from "@/components/note-merge-dialog";
import { NoteSplitControl } from "@/components/note-split-control";

type LinkRow = {
  id: string;
  target_note_id?: string;
  source_note_id?: string;
  kind: string;
  custom_label: string | null;
  origin: string;
  link_reason?: string | null;
  link_strength?: number | null;
};

type NoteDetail = {
  id: string;
  title: string;
  body: string;
  tags: string[];
  origin: string;
  updated_at: string;
  agent_id?: string | null;
  memory_context?: string | null;
  memory_keywords?: string[] | null;
  dreaming_touched_at?: string | null;
  evolution_history?: unknown[] | null;
  links_out: LinkRow[];
  links_in: LinkRow[];
  source_episodes: Array<{ id: string; document_id?: string; page_start?: number | null; page_end?: number | null }>;
};

const LINK_KINDS = ["related", "supports", "refutes", "extends", "references", "custom"] as const;

export function NoteDetail({
  workspaceId,
  noteId,
  mergeOpen,
  onOpenMerge,
  onCloseMerge,
  onMerged,
  onSplitCreated,
  onDeleted,
}: {
  workspaceId: string;
  noteId: string;
  mergeOpen: boolean;
  onOpenMerge: () => void;
  onCloseMerge: () => void;
  onMerged: (id: string) => void;
  onSplitCreated: (newId: string) => void;
  onDeleted: () => void;
}) {
  const [note, setNote] = useState<NoteDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [tagsRaw, setTagsRaw] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [selection, setSelection] = useState<string | null>(null);
  const [splitBusy, setSplitBusy] = useState(false);

  const [targetLink, setTargetLink] = useState("");
  const [kindLink, setKindLink] = useState<string>("related");
  const [customLabel, setCustomLabel] = useState("");

  const taRef = useRef<HTMLTextAreaElement>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inflight = useRef<AbortController | null>(null);
  const baseline = useRef({ title: "", body: "", tags: "" });
  const toast = useToast();
  const confirm = useConfirm();
  const prompt = usePrompt();

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/notes/${noteId}`, { cache: "no-store" });
      const raw = await res.text();
      let j: NoteDetail & { error?: { message?: string } };
      try {
        j = JSON.parse(raw) as typeof j;
      } catch {
        setNote(null);
        setLoadError(
          res.ok
            ? "Invalid response from server"
            : `Request failed (${res.status}). The server did not return JSON — check pipeline logs.`,
        );
        return;
      }
      if (!res.ok) {
        setNote(null);
        setLoadError((j as { error?: { message?: string } }).error?.message ?? "Failed to load note");
        return;
      }
      setNote(j);
      setTitle(j.title ?? "");
      setBody(j.body ?? "");
      setTagsRaw((j.tags ?? []).join(", "));
      baseline.current = {
        title: j.title ?? "",
        body: j.body ?? "",
        tags: (j.tags ?? []).join(", "),
      };
      setSaveState("idle");
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load note");
    }
  }, [workspaceId, noteId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const dirty =
      title !== baseline.current.title ||
      body !== baseline.current.body ||
      tagsRaw !== baseline.current.tags;
    if (!dirty) return;

    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      inflight.current?.abort();
      inflight.current = new AbortController();
      setSaveState("saving");
      const tags = tagsRaw
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      try {
        const res = await fetch(`/api/v1/workspaces/${workspaceId}/notes/${noteId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          signal: inflight.current.signal,
          body: JSON.stringify({ title, body, tags }),
        });
        if (!res.ok) {
          setSaveState("error");
          return;
        }
        baseline.current = { title, body, tags: tagsRaw };
        setSaveState("saved");
        await load();
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        setSaveState("error");
      }
    }, 750);

    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [title, body, tagsRaw, workspaceId, noteId, load]);

  const captureSelection = () => {
    const el = taRef.current;
    if (!el) return;
    const s = el.selectionStart;
    const e = el.selectionEnd;
    if (s === e) {
      setSelection(null);
      return;
    }
    const slice = el.value.slice(s, e);
    setSelection(slice || null);
  };

  const doSplit = async () => {
    if (!selection?.trim()) return;
    const nt = await prompt({
      title: "Name the new note",
      description: `The selected ${selection.length} characters will be moved into a new note linked to this one (extends).`,
      label: "Title",
      defaultValue: "Split note",
      placeholder: "Title for the new note",
      confirmLabel: "Create split",
      required: true,
      maxLength: 200,
    });
    if (!nt?.trim()) return;
    setSplitBusy(true);
    try {
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/notes/${noteId}/split`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passage: selection, new_title: nt.trim() }),
      });
      const raw = await res.text();
      const j = JSON.parse(raw) as { note?: { id: string }; error?: { message?: string } };
      if (!res.ok) {
        toast({
          variant: "error",
          message: "Split failed",
          description: j.error?.message,
        });
        return;
      }
      if (j.note?.id) {
        setSelection(null);
        await load();
        onSplitCreated(j.note.id);
      }
    } catch {
      toast({ variant: "error", message: "Split failed" });
    } finally {
      setSplitBusy(false);
    }
  };

  const addLink = async () => {
    if (!targetLink.trim()) return;
    const payload: Record<string, unknown> = {
      target_note_id: targetLink.trim(),
      kind: kindLink,
    };
    if (kindLink === "custom") {
      payload.custom_label = customLabel.trim() || "link";
    }
    const res = await fetch(`/api/v1/workspaces/${workspaceId}/notes/${noteId}/links`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const j = (await res.json()) as { error?: { message?: string } };
      toast({
        variant: "error",
        message: "Could not add link",
        description: j.error?.message,
      });
      return;
    }
    setTargetLink("");
    setCustomLabel("");
    await load();
    toast({ variant: "success", message: "Link added" });
  };

  const removeLink = async (linkId: string) => {
    const res = await fetch(`/api/v1/workspaces/${workspaceId}/notes/${noteId}/links/${linkId}`, {
      method: "DELETE",
    });
    if (!res.ok) return;
    await load();
  };

  const delNote = async () => {
    const ok = await confirm({
      title: "Delete note?",
      description: "This note will be permanently removed. Linked notes are preserved.",
      confirmLabel: "Delete note",
      variant: "danger",
    });
    if (!ok) return;
    const res = await fetch(`/api/v1/workspaces/${workspaceId}/notes/${noteId}`, { method: "DELETE" });
    if (res.ok) {
      toast({ variant: "success", message: "Note deleted" });
      onDeleted();
    } else {
      toast({ variant: "error", message: "Could not delete note" });
    }
  };

  if (loadError) {
    return (
      <div className="rounded-md border border-red-500/40 bg-red-500/10 p-4 text-caption text-red-200">
        {loadError}
      </div>
    );
  }

  if (!note) {
    return <p className="text-caption text-muted">Loading note…</p>;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto">
      <NoteMergeDialog
        open={mergeOpen}
        workspaceId={workspaceId}
        survivorNoteId={noteId}
        onClose={onCloseMerge}
        onMerged={onMerged}
      />

      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <label className="sr-only" htmlFor="note-title">
            Title
          </label>
          <input
            id="note-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full border-b border-transparent bg-transparent text-title-3 text-secondary outline-none focus:border-accent-primary"
          />
          <p className="mt-1 text-caption text-muted">
            <span className="capitalize">{note.origin}</span>
            {note.origin === "manual" ? (
              <span className="ml-2 rounded bg-amber-500/20 px-1.5 py-0.5 text-amber-100">Manual</span>
            ) : null}
            · Updated {new Date(note.updated_at).toLocaleString()}
            {note.agent_id ? (
              <span className="ml-2 font-mono text-muted">· agent {note.agent_id}</span>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-caption text-muted" aria-live="polite">
            {saveState === "saving" ? "Saving…" : null}
            {saveState === "saved" ? "Saved" : null}
            {saveState === "error" ? "Save error" : null}
          </span>
          <button
            type="button"
            className="rounded-md border border-border-strong px-2 py-1 text-caption text-secondary"
            onClick={onOpenMerge}
          >
            Merge…
          </button>
          <button
            type="button"
            className="rounded-md border border-red-500/50 px-2 py-1 text-caption text-red-200"
            onClick={() => void delNote()}
          >
            Delete
          </button>
        </div>
      </header>

      {(note.memory_context ||
        (note.memory_keywords && note.memory_keywords.length > 0) ||
        note.dreaming_touched_at) ? (
        <section
          aria-label="Agent memory"
          className="rounded-md border border-border-subtle bg-surface/40 p-3 text-caption text-secondary"
        >
          <p className="font-medium text-primary">A-MEM / dreaming</p>
          {note.memory_context ? (
            <p className="mt-2">
              <span className="text-muted">Context: </span>
              {note.memory_context}
            </p>
          ) : null}
          {note.memory_keywords && note.memory_keywords.length > 0 ? (
            <p className="mt-2">
              <span className="text-muted">Keywords: </span>
              {note.memory_keywords.join(", ")}
            </p>
          ) : null}
          {note.dreaming_touched_at ? (
            <p className="mt-2 text-muted">
              Dreaming touched {new Date(note.dreaming_touched_at).toLocaleString()}
            </p>
          ) : null}
        </section>
      ) : null}

      <label className="block text-caption text-muted">
        Tags (comma-separated)
        <input
          value={tagsRaw}
          onChange={(e) => setTagsRaw(e.target.value)}
          className="mt-1 w-full rounded-md border border-border-strong bg-surface px-2 py-1 text-body text-secondary"
        />
      </label>

      <NoteSplitControl selection={selection} busy={splitBusy} onSplit={() => void doSplit()} />

      <label className="block text-caption text-muted">
        Body
        <textarea
          ref={taRef}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onSelect={captureSelection}
          onKeyUp={captureSelection}
          onMouseUp={captureSelection}
          rows={16}
          className="mt-1 w-full max-w-[68ch] rounded-md border border-border-strong bg-surface px-3 py-2 font-serif text-body leading-relaxed text-secondary"
        />
      </label>

      <section aria-label="Source episodes" className="text-caption text-muted">
        <p className="font-medium text-secondary">Source episodes</p>
        {note.source_episodes?.length ? (
          <ul className="mt-1 list-inside list-disc">
            {note.source_episodes.map((se) => (
              <li key={se.id} className="font-mono">
                {se.id}
                {se.document_id ? ` · doc ${se.document_id}` : ""}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1">None (manual or detached).</p>
        )}
      </section>

      <section aria-label="Links" className="space-y-3">
        <p className="text-body font-medium text-secondary">Links</p>
        <div className="flex flex-wrap gap-2 rounded-md border border-border-subtle bg-surface/40 p-2">
          <input
            placeholder="Target note uuid"
            value={targetLink}
            onChange={(e) => setTargetLink(e.target.value)}
            className="min-w-[12rem] flex-1 rounded-md border border-border-strong bg-surface px-2 py-1 font-mono text-caption"
          />
          <select
            value={kindLink}
            onChange={(e) => setKindLink(e.target.value)}
            className="rounded-md border border-border-strong bg-surface px-2 py-1 text-caption"
          >
            {LINK_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          {kindLink === "custom" ? (
            <input
              placeholder="Custom label"
              value={customLabel}
              onChange={(e) => setCustomLabel(e.target.value)}
              className="rounded-md border border-border-strong bg-surface px-2 py-1 text-caption"
            />
          ) : null}
          <button
            type="button"
            className="rounded-md bg-accent-primary px-2 py-1 text-caption font-medium text-canvas"
            onClick={() => void addLink()}
          >
            Add link
          </button>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <p className="text-caption font-medium text-muted">Outgoing</p>
            <ul className="mt-1 space-y-1">
              {note.links_out.map((l) => (
                <li key={l.id} className="flex items-center justify-between gap-2 text-caption text-secondary">
                  <span>
                    → {l.target_note_id}{" "}
                    <span className="text-muted">
                      ({l.kind}
                      {l.custom_label ? `: ${l.custom_label}` : ""}
                      {l.link_reason ? ` · ${l.link_reason}` : ""}
                      {l.link_strength != null ? ` · strength ${l.link_strength}` : ""})
                    </span>
                  </span>
                  <button
                    type="button"
                    className="text-red-300 hover:underline"
                    onClick={() => void removeLink(l.id)}
                  >
                    Remove
                  </button>
                </li>
              ))}
              {note.links_out.length === 0 ? <li className="text-muted">None</li> : null}
            </ul>
          </div>
          <div>
            <p className="text-caption font-medium text-muted">Incoming</p>
            <ul className="mt-1 space-y-1">
              {note.links_in.map((l) => (
                <li key={l.id} className="text-caption text-secondary">
                  ← {l.source_note_id}{" "}
                  <span className="text-muted">
                    ({l.kind}
                    {l.custom_label ? `: ${l.custom_label}` : ""}
                    {l.link_reason ? ` · ${l.link_reason}` : ""}
                    {l.link_strength != null ? ` · strength ${l.link_strength}` : ""})
                  </span>
                </li>
              ))}
              {note.links_in.length === 0 ? <li className="text-muted">None</li> : null}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}
