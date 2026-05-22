'use client';

import { cva } from 'class-variance-authority';
import { Tooltip as TooltipPrimitive } from 'radix-ui';
import * as React from 'react';

import { useDirection } from '@/lib/north-ui/direction';
import { Slot } from '@/lib/north-ui/slot';
import { cn } from '@/lib/north-ui/cn';

const tooltipVariants = cva(
  'animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 origin-(--radix-tooltip-content-transform-origin) z-tooltip flex w-fit transform-gpu items-center gap-1.5 text-balance rounded-md border px-3 py-1.5 text-xs will-change-[transform,opacity]',
  {
    variants: {
      variant: {
        default: 'bg-foreground text-background border-foreground border',
        outline: 'bg-card text-card-foreground border-border border',
        primary: 'bg-primary text-primary-foreground'
      }
    },
    defaultVariants: {
      variant: 'default'
    }
  }
);

const arrowVariants = cva('z-tooltip fill-card -mt-[2px] border-none', {
  variants: {
    variant: {
      default: 'fill-foreground drop-shadow-[0_2px_0_var(--foreground)]',
      outline: 'fill-card drop-shadow-[0_2px_0_var(--border)]',
      primary: 'fill-primary'
    }
  },
  defaultVariants: {
    variant: 'default'
  }
});

function TooltipProvider({
  delayDuration = 0,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
  return (
    <TooltipPrimitive.Provider
      data-slot={Slot.TOOLTIP_PROVIDER}
      delayDuration={delayDuration}
      {...props}
    />
  );
}

function Tooltip({ ...props }: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  return (
    <TooltipProvider>
      <TooltipPrimitive.Root data-slot={Slot.TOOLTIP} {...props} />
    </TooltipProvider>
  );
}

function TooltipTrigger({ ...props }: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
  const dir = useDirection();

  return <TooltipPrimitive.Trigger data-slot={Slot.TOOLTIP_TRIGGER} dir={dir} {...props} />;
}

interface TooltipContentProps extends React.ComponentProps<typeof TooltipPrimitive.Content> {
  variant?: 'default' | 'outline' | 'primary';
  withArrow?: boolean;
}

function TooltipContent({
  className,
  variant = 'default',
  withArrow = true,
  sideOffset = 6,
  children,
  ...props
}: TooltipContentProps) {
  const dir = useDirection();

  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        data-slot={Slot.TOOLTIP_CONTENT}
        dir={dir}
        sideOffset={sideOffset}
        className={cn(tooltipVariants({ variant, className }))}
        {...props}
      >
        {children}
        {withArrow && (
          <TooltipPrimitive.Arrow className={cn(arrowVariants({ variant }))} aria-hidden="true" />
        )}
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  );
}

// @see: https://github.com/FranciscoMoretti/shadcn-lazy-tooltip
function LazyTooltip({
  open,
  defaultOpen,
  onOpenChange,
  delayDuration = 0,
  disableHoverableContent,
  content,
  children,
  asChild = true,
  ...tooltipContentProps
}: {
  content: React.ReactNode;
  children: React.ReactElement;
  asChild?: boolean;
} & Pick<
  React.ComponentProps<typeof TooltipContent>,
  'align' | 'side' | 'alignOffset' | 'sideOffset' | 'variant' | 'withArrow' | 'className'
> &
  React.ComponentProps<typeof TooltipPrimitive.Root>) {
  const [enabled, setEnabled] = React.useState(false);

  const handlePointerEnter = React.useCallback(() => setEnabled(true), []);
  const handleTouchStart = React.useCallback(() => setEnabled(true), []);

  const triggerProps = {
    onPointerEnter: handlePointerEnter,
    onTouchStart: handleTouchStart
  } as const;

  if (!enabled) {
    // Clone to attach events without mounting Tooltip tree
    return React.cloneElement(children, triggerProps);
  }

  return (
    <Tooltip
      delayDuration={delayDuration}
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
      disableHoverableContent={disableHoverableContent}
    >
      <TooltipTrigger asChild={asChild}>
        {React.cloneElement(children, triggerProps)}
      </TooltipTrigger>
      <TooltipContent {...tooltipContentProps}>{content}</TooltipContent>
    </Tooltip>
  );
}

export { LazyTooltip, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger };
