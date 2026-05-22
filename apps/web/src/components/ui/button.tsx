import { type VariantProps, cva } from 'class-variance-authority';
import { Slot as SlotPrimitive } from 'radix-ui';
import * as React from 'react';

import { Slot } from '@/lib/north-ui/slot';
import { cn } from '@/lib/north-ui/cn';

const buttonVariants = cva(
  'focus-visible:border-ring focus-visible:outline-ring/50 aria-invalid:outline-destructive/20 dark:aria-invalid:outline-destructive/40 aria-invalid:border-destructive inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all focus-visible:outline-[3px] disabled:cursor-not-allowed disabled:opacity-50 [&_span[role="img"]]:pointer-events-none [&_span[role="img"]]:shrink-0 [&_svg]:pointer-events-none [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        default:
          'bg-primary text-primary-foreground fill-primary-foreground shadow-xs hover:bg-primary/90',
        destructive:
          'bg-destructive text-destructive-foreground fill-destructive-foreground shadow-xs hover:bg-destructive/90 focus-visible:outline-destructive/20 dark:focus-visible:outline-destructive/40 dark:bg-destructive/60',
        outline:
          'bg-background text-foreground fill-foreground shadow-xs hover:bg-accent hover:text-accent-foreground hover:fill-accent-foreground dark:bg-input/20 dark:border-input dark:hover:bg-input/50 border',
        secondary:
          'bg-secondary text-secondary-foreground fill-secondary-foreground shadow-xs hover:bg-secondary/80',
        ghost:
          'hover:bg-accent text-foreground fill-foreground hover:text-accent-foreground hover:fill-accent-foreground dark:hover:bg-accent/50',
        link: 'text-primary fill-primary underline-offset-4 hover:underline'
      },
      size: {
        default: 'h-9 px-4 py-2 has-[>span[role="img"]]:px-3 has-[>svg]:px-3',
        sm: 'h-7 gap-1.5 rounded-md px-2 has-[>span[role="img"]]:px-2.5 has-[>svg]:px-2.5',
        lg: 'h-10 rounded-md px-6 has-[>span[role="img"]]:px-4 has-[>svg]:px-4',
        xl: 'h-12 rounded-md px-8 has-[>span[role="img"]]:px-6 has-[>svg]:px-6',
        icon: 'size-8'
      }
    },
    defaultVariants: {
      variant: 'default',
      size: 'default'
    }
  }
);

export type ButtonProps = React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  };

function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Comp = asChild ? SlotPrimitive.Slot : 'button';

  return (
    <Comp
      data-slot={Slot.BUTTON}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

export { Button, buttonVariants };
