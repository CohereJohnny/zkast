'use client';

import { Label as LabelPrimitive } from 'radix-ui';
import * as React from 'react';

import { Slot } from '@/lib/north-ui/slot';
import { cn } from '@/lib/north-ui/cn';

function Label({ className, ...props }: React.ComponentProps<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      data-slot={Slot.LABEL}
      className={cn(
        'flex select-none items-center gap-2 text-sm leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-50 group-data-[disabled=true]:pointer-events-none group-data-[disabled=true]:opacity-50',
        className
      )}
      {...props}
    />
  );
}

export { Label };
