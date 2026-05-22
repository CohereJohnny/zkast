import { type VariantProps, cva } from 'class-variance-authority';
import { Slot as SlotPrimitive } from 'radix-ui';
import * as React from 'react';

import { Slot } from '../lib/slot';
import { cn } from '../lib/cn';

const badgeVariants = cva(
  'focus-visible:border-ring focus-visible:outline-ring/50 aria-invalid:outline-destructive/20 dark:aria-invalid:outline-destructive/40 aria-invalid:border-destructive inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-semibold transition-[color,box-shadow] focus-visible:outline-[3px] [&>span[role="img"]]:pointer-events-none [&>span[role="img"]]:size-3 [&>svg]:pointer-events-none [&>svg]:size-3',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground [a&]:hover:bg-primary/90 border-transparent',
        success: 'bg-success text-success-foreground [a&]:hover:bg-success/90 border-transparent',
        caution: 'bg-caution text-caution-foreground [a&]:hover:bg-caution/90 border-transparent',
        secondary:
          'bg-secondary text-secondary-foreground [a&]:hover:bg-secondary/90 border-transparent',
        destructive:
          'bg-destructive text-destructive-foreground [a&]:hover:bg-destructive/90 focus-visible:outline-destructive/20 dark:focus-visible:outline-destructive/40 dark:bg-destructive/60 border-transparent',
        outline:
          'bg-background text-foreground [a&]:hover:bg-accent [a&]:hover:text-accent-foreground',
        info: 'bg-highlight text-highlight-foreground border-transparent'
      }
    },
    defaultVariants: {
      variant: 'default'
    }
  }
);

function Badge({
  className,
  variant,
  asChild = false,
  ...props
}: React.ComponentProps<'span'> & VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? SlotPrimitive.Slot : 'span';

  return (
    <Comp data-slot={Slot.BADGE} className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
