import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type EmptyStateProps = {
  title: string;
  description: string;
  cta?: ReactNode;
  className?: string;
};

/**
 * Empty state pattern from specs/uiux.md States Reference.
 */
export function EmptyState({
  title,
  description,
  cta,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-4 px-6 py-12 text-center",
        className,
      )}
    >
      <div
        className="flex h-28 w-40 items-center justify-center rounded-lg border border-dashed border-input bg-secondary/40 text-caption text-muted-foreground"
        aria-hidden
      >
        Illustration placeholder
      </div>
      <div className="max-w-md space-y-2">
        <h1 className="text-h2 font-semibold text-foreground">{title}</h1>
        <p className="text-p text-muted-foreground">{description}</p>
      </div>
      {cta ? <div className="flex justify-center">{cta}</div> : null}
    </div>
  );
}
