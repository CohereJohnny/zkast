"use client";

import { MessageSquare } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

/**
 * Collapsed chat drawer affordance (full drawer in later sprints).
 */
export function ChatDrawerSlot() {
  const [open, setOpen] = useState(false);

  return (
    <div
      className={cn(
        "fixed right-4 top-1/2 z-30 flex -translate-y-1/2 flex-col items-end gap-2 transition-[width]",
        open ? "w-72" : "w-11",
      )}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls="chat-drawer-panel"
        className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-l-lg border border-border border-r-0 bg-card text-text-link shadow-lg hover:bg-secondary"
        onClick={() => setOpen((v) => !v)}
      >
        <MessageSquare className="h-5 w-5" strokeWidth={1.5} aria-hidden />
        <span className="sr-only">Toggle chat drawer</span>
      </button>
      <div
        id="chat-drawer-panel"
        hidden={!open}
        className="w-full rounded-lg border border-border bg-card p-4 text-caption text-muted-foreground shadow-lg"
      >
        Chat drawer placeholder — opens over the workspace in later sprints.
      </div>
    </div>
  );
}
