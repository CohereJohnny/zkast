"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { useToast } from "@/components/feedback-provider";
import { NoteDetail } from "@/components/note-detail";
import { NotesList, type NoteListItem } from "@/components/notes-list";
import type { SourceScopeSelection } from "@/components/filters/source-scope-filter";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function NotesPageClient({ workspaceId }: { workspaceId: string }) {
  const searchParams = useSearchParams();
  const [items, setItems] = useState<NoteListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [qInput, setQInput] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [origin, setOrigin] = useState("");
  const [source, setSource] = useState<SourceScopeSelection | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mergeOpen, setMergeOpen] = useState(false);
  const toast = useToast();

  useEffect(() => {
    const t = window.setTimeout(() => setQDebounced(qInput), 400);
    return () => window.clearTimeout(t);
  }, [qInput]);

  useEffect(() => {
    const agentFromUrl = searchParams.get("agentId") ?? searchParams.get("agent_id");
    const docFromUrl = searchParams.get("document_id") ?? searchParams.get("documentId");
    if (agentFromUrl && UUID_RE.test(agentFromUrl)) {
      setSource({ kind: "agent", id: agentFromUrl });
    } else if (docFromUrl && UUID_RE.test(docFromUrl)) {
      setSource({ kind: "document", id: docFromUrl });
    }
  }, [searchParams]);

  const refreshList = useCallback(async () => {
    setListError(null);
    setListLoading(true);
    try {
      const qs = new URLSearchParams();
      if (qDebounced.trim()) qs.set("q", qDebounced.trim());
      if (origin) qs.set("origin", origin);
      if (source && UUID_RE.test(source.id)) {
        qs.set(source.kind === "agent" ? "agent_id" : "document_id", source.id);
      }
      qs.set("limit", "100");
      qs.set("offset", "0");
      const res = await fetch(`/api/v1/workspaces/${workspaceId}/notes?${qs.toString()}`, {
        cache: "no-store",
      });
      const j = (await res.json()) as {
        items?: NoteListItem[];
        total?: number;
        error?: { message?: string };
      };
      if (!res.ok) {
        setListError(j.error?.message ?? "Failed to load notes");
        return;
      }
      setItems(j.items ?? []);
      setTotal(j.total ?? 0);
    } catch (e) {
      setListError(e instanceof Error ? e.message : "Failed to load notes");
    } finally {
      setListLoading(false);
    }
  }, [workspaceId, qDebounced, origin, source]);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  const newNote = async () => {
    const res = await fetch(`/api/v1/workspaces/${workspaceId}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Untitled note", body: "", tags: [] }),
    });
    const raw = await res.text();
    try {
      const j = JSON.parse(raw) as { note?: { id: string }; error?: { message?: string } };
      if (!res.ok) {
        toast({
          variant: "error",
          message: "Could not create note",
          description: j.error?.message,
        });
        return;
      }
      if (j.note?.id) {
        setSelectedId(j.note.id);
        await refreshList();
        toast({ variant: "success", message: "Note created" });
      }
    } catch {
      toast({ variant: "error", message: "Could not create note" });
    }
  };

  return (
    <div className="flex min-h-[520px] flex-col gap-4 p-2">
      <header>
        <h1 className="text-h4 text-muted-foreground">Notes</h1>
        <p className="mt-1 max-w-2xl text-caption text-muted-foreground">
          Atomic notes from ingestion and manual entries. Edits autosave; merge and split preserve provenance via the
          pipeline.
        </p>
        <p className="mt-1 text-caption text-muted-foreground">{total} notes</p>
      </header>

      <div className="grid min-h-0 flex-1 gap-4 md:grid-cols-[minmax(240px,320px)_1fr]">
        <NotesList
          items={items}
          selectedId={selectedId}
          onSelect={setSelectedId}
          loading={listLoading}
          error={listError}
          q={qInput}
          origin={origin}
          source={source}
          onQChange={setQInput}
          onOriginChange={setOrigin}
          onSourceChange={setSource}
          onNewNote={() => void newNote()}
          workspaceId={workspaceId}
        />

        <div className="min-h-[320px] rounded-lg border border-border bg-card/30 p-4">
          {selectedId ? (
            <NoteDetail
              workspaceId={workspaceId}
              noteId={selectedId}
              mergeOpen={mergeOpen}
              onOpenMerge={() => setMergeOpen(true)}
              onCloseMerge={() => setMergeOpen(false)}
              onMerged={(id) => {
                setMergeOpen(false);
                setSelectedId(id);
                void refreshList();
              }}
              onSplitCreated={(newId) => {
                setSelectedId(newId);
                void refreshList();
                toast({
                  variant: "success",
                  message: "Split created new note",
                  description: `Bookmark: /notes?note=${newId}`,
                  durationMs: 6000,
                });
              }}
              onDeleted={() => {
                setSelectedId(null);
                void refreshList();
              }}
            />
          ) : (
            <p className="text-caption text-muted-foreground">Select a note or create a new one.</p>
          )}
        </div>
      </div>
    </div>
  );
}
