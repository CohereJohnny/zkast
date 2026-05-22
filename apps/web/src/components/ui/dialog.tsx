'use client';

import { Dialog as DialogPrimitive } from 'radix-ui';
import * as React from 'react';

import { X } from 'lucide-react';
import { Slot } from '@/lib/north-ui/slot';
import { cn } from '@/lib/north-ui/cn';
import { useAsRef } from '@/lib/north-ui/use-as-ref';
import { ModalContext } from '@/lib/north-ui/modal-context';

function Dialog({ ...props }: React.ComponentProps<typeof DialogPrimitive.Root>) {
  return <DialogPrimitive.Root data-slot={Slot.DIALOG} {...props} />;
}

function DialogTrigger({ ...props }: React.ComponentProps<typeof DialogPrimitive.Trigger>) {
  return <DialogPrimitive.Trigger data-slot={Slot.DIALOG_TRIGGER} {...props} />;
}

function DialogPortal({ ...props }: React.ComponentProps<typeof DialogPrimitive.Portal>) {
  return <DialogPrimitive.Portal data-slot={Slot.DIALOG_PORTAL} {...props} />;
}

function DialogClose({ ...props }: React.ComponentProps<typeof DialogPrimitive.Close>) {
  return <DialogPrimitive.Close data-slot={Slot.DIALOG_CLOSE} {...props} />;
}

function DialogOverlay({
  className,
  children,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Overlay>) {
  return (
    <DialogPrimitive.Overlay
      data-slot={Slot.DIALOG_OVERLAY}
      className={cn(
        'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 bg-muted/50 z-backdrop fixed inset-0',
        className
      )}
      {...props}
    >
      {children}
    </DialogPrimitive.Overlay>
  );
}

function DialogContent({
  className,
  children,
  container,
  buttonClassName,
  overlayClassName,
  showCloseButton = true,
  closeOnClickOutside = true,
  onPointerDownOutside: onPointerDownOutsideProp,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & {
  container?: React.ComponentProps<typeof DialogPrimitive.Portal>['container'];
  buttonClassName?: string;
  overlayClassName?: string;
  showCloseButton?: boolean;
  closeOnClickOutside?: boolean;
}) {
  const propsRef = useAsRef({
    closeOnClickOutside,
    onPointerDownOutside: onPointerDownOutsideProp
  });

  const onPointerDownOutside: NonNullable<
    React.ComponentProps<typeof DialogPrimitive.Content>['onPointerDownOutside']
  > = React.useCallback(
    (event) => {
      propsRef.current.onPointerDownOutside?.(event);

      if (event.defaultPrevented) return;

      if (!propsRef.current.closeOnClickOutside) {
        event.preventDefault();
        return;
      }

      const isClickedOnToast = (event.composedPath?.() ?? []).some(
        (element) =>
          element instanceof Element &&
          (element.hasAttribute('data-sonner-toaster') || element.hasAttribute('data-sonner-toast'))
      );

      if (isClickedOnToast) {
        event.preventDefault();
      }
    },
    [propsRef]
  );

  return (
    <DialogPortal data-slot={Slot.DIALOG_PORTAL} container={container}>
      <ModalContext.Provider value={true}>
        <DialogOverlay className={overlayClassName} />
        <DialogPrimitive.Content
          data-slot={Slot.DIALOG_CONTENT}
          className={cn(
            'bg-background data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 z-modal fixed left-[50%] top-[50%] w-full max-w-[calc(100%-2rem)] translate-x-[-50%] translate-y-[-50%] gap-4 rounded-lg border p-6 shadow-lg duration-200 sm:max-w-lg',
            'max-h-modal lg:max-w-modal',
            'flex flex-col',
            className
          )}
          onPointerDownOutside={onPointerDownOutside}
          {...props}
        >
          {children}
          {showCloseButton && (
            <DialogPrimitive.Close
              className={cn(
                `data-[state=open]:bg-accent data-[state=open]:text-muted-foreground focus:outline-ring rounded-xs absolute opacity-70 outline-none transition-opacity hover:opacity-100 focus:outline-2 focus:outline-offset-2 disabled:pointer-events-none [&_span[role="img"]:not([class*='size-'])]:size-4 [&_span[role="img"]]:pointer-events-none [&_span[role="img"]]:shrink-0 [&_svg:not([class*='size-'])]:size-4 [&_svg]:pointer-events-none [&_svg]:shrink-0`,
                'top-4 ltr:right-4 rtl:left-4',
                buttonClassName
              )}
            >
              <X className="size-4" aria-hidden />
              <span className="sr-only">Close</span>
            </DialogPrimitive.Close>
          )}
        </DialogPrimitive.Content>
      </ModalContext.Provider>
    </DialogPortal>
  );
}

function DialogHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot={Slot.DIALOG_HEADER}
      className={cn('flex flex-col gap-2', className)}
      {...props}
    />
  );
}

function DialogBody({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot={Slot.DIALOG_BODY}
      className={cn('min-h-0 flex-1 overflow-y-auto', className)}
      {...props}
    />
  );
}

function DialogFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot={Slot.DIALOG_FOOTER}
      className={cn('flex flex-col-reverse gap-2 sm:flex-row sm:justify-end', className)}
      {...props}
    />
  );
}

function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      data-slot={Slot.DIALOG_TITLE}
      className={cn('text-lg font-semibold leading-none', className)}
      {...props}
    />
  );
}

function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      data-slot={Slot.DIALOG_DESCRIPTION}
      className={cn('text-muted-foreground text-sm', className)}
      {...props}
    />
  );
}

export {
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger
};
