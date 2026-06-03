"use client";

import {
  Activity,
  BarChart3,
  BookOpen,
  Bot,
  Boxes,
  FileText,
  LayoutDashboard,
  MessageSquare,
  Network,
  ScrollText,
  Settings,
  Slack,
  StickyNote,
  Camera,
  Target,
  Workflow,
  Layers,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const items = [
  { href: "/dashboard", label: "Dashboard", Icon: LayoutDashboard },
  { href: "/agents", label: "Agents", Icon: Bot },
  { href: "/conversations", label: "Conversations", Icon: ScrollText },
  { href: "/slack", label: "Slack", Icon: Slack },
  { href: "/documents", label: "Documents", Icon: FileText },
  { href: "/jobs", label: "Jobs", Icon: Activity },
  { href: "/notes", label: "Notes", Icon: StickyNote },
  { href: "/graph", label: "Graph", Icon: Network },
  { href: "/ontologies", label: "Ontologies", Icon: Boxes },
  { href: "/graphrag", label: "GraphRAG", Icon: Workflow },
  { href: "/pipelines", label: "Pipelines", Icon: Layers },
  { href: "/wiki", label: "Wiki", Icon: BookOpen },
  { href: "/chat", label: "Chat", Icon: MessageSquare },
  { href: "/evals", label: "Evals", Icon: BarChart3 },
  { href: "/snapshots", label: "Snapshots", Icon: Camera },
  { href: "/targets", label: "External Targets", Icon: Target },
  { href: "/settings", label: "Settings", Icon: Settings },
] as const;

export function LeftRail({ workspaceName }: { workspaceName: string }) {
  const pathname = usePathname();

  return (
    <aside
      aria-label="Primary navigation"
      className="fixed left-4 top-4 bottom-4 z-40 flex w-52 flex-col rounded-lg border border-border bg-card py-3 shadow-lg"
    >
      <div className="border-b border-border px-3 pb-3">
        <p className="truncate text-caption text-muted-foreground">Workspace</p>
        <p className="truncate text-h5 text-foreground">{workspaceName}</p>
      </div>
      <nav className="mt-2 flex flex-1 flex-col gap-0.5 px-2">
        {items.map(({ href, label, Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-p text-muted-foreground transition hover:bg-secondary hover:text-foreground",
                active && "bg-secondary text-foreground",
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
