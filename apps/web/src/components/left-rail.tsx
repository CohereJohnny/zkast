"use client";

import {
  Activity,
  BookOpen,
  Bot,
  FileText,
  MessageSquare,
  Network,
  ScrollText,
  Settings,
  StickyNote,
  Camera,
  Target,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const items = [
  { href: "/agents", label: "Agents", Icon: Bot },
  { href: "/conversations", label: "Conversations", Icon: ScrollText },
  { href: "/documents", label: "Documents", Icon: FileText },
  { href: "/jobs", label: "Jobs", Icon: Activity },
  { href: "/notes", label: "Notes", Icon: StickyNote },
  { href: "/graph", label: "Graph", Icon: Network },
  { href: "/wiki", label: "Wiki", Icon: BookOpen },
  { href: "/chat", label: "Chat", Icon: MessageSquare },
  { href: "/snapshots", label: "Snapshots", Icon: Camera },
  { href: "/targets", label: "External Targets", Icon: Target },
  { href: "/settings", label: "Settings", Icon: Settings },
] as const;

export function LeftRail({ workspaceName }: { workspaceName: string }) {
  const pathname = usePathname();

  return (
    <aside
      aria-label="Primary navigation"
      className="fixed left-4 top-4 bottom-4 z-40 flex w-52 flex-col rounded-lg border border-border-subtle bg-surface py-3 shadow-modal"
    >
      <div className="border-b border-border-subtle px-3 pb-3">
        <p className="truncate text-caption text-muted">Workspace</p>
        <p className="truncate text-title-3 text-primary">{workspaceName}</p>
      </div>
      <nav className="mt-2 flex flex-1 flex-col gap-0.5 px-2">
        {items.map(({ href, label, Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-body text-secondary transition hover:bg-surface-raised hover:text-primary",
                active && "bg-surface-raised text-primary",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" strokeWidth={1.5} aria-hidden />
              <span className="truncate">{label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
