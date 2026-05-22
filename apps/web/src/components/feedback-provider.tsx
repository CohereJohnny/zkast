"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

type ToastVariant = "success" | "error" | "warning" | "info";

type Toast = {
  id: string;
  message: string;
  description?: string;
  variant: ToastVariant;
};

type ToastInput = {
  message: string;
  description?: string;
  variant?: ToastVariant;
  durationMs?: number;
};

type ConfirmInput = {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "default" | "danger";
};

type PromptInput = {
  title: string;
  description?: string;
  label?: string;
  placeholder?: string;
  defaultValue?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  maxLength?: number;
  required?: boolean;
};

type FeedbackContextValue = {
  toast: (opts: ToastInput) => void;
  confirm: (opts: ConfirmInput) => Promise<boolean>;
  prompt: (opts: PromptInput) => Promise<string | null>;
};

const FeedbackContext = createContext<FeedbackContextValue | null>(null);

const MAX_TOASTS = 4;
const DEFAULT_DURATION_MS = 4000;

function variantClasses(variant: ToastVariant): {
  container: string;
  iconPath: string;
} {
  switch (variant) {
    case "success":
      return {
        container:
          "border-success/40 bg-success/12 text-success-foreground shadow-lg",
        iconPath:
          "M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
      };
    case "error":
      return {
        container:
          "border-destructive/40 bg-destructive/12 text-destructive-foreground shadow-lg",
        iconPath:
          "M12 9v3.75m0 3.75h.008v.008H12V16.5Zm9.75-4.5a9.75 9.75 0 1 1-19.5 0 9.75 9.75 0 0 1 19.5 0Z",
      };
    case "warning":
      return {
        container:
          "border-caution/40 bg-caution/12 text-caution-foreground shadow-lg",
        iconPath:
          "M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z",
      };
    case "info":
    default:
      return {
        container:
          "border-border bg-secondary text-foreground shadow-lg",
        iconPath:
          "M11.25 11.25 12 12m0 0 .75.75M12 12V8.25m0 7.5h.008v.008H12v-.008ZM21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z",
      };
  }
}

function ToastIcon({ d }: { d: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-5 w-5 shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={d} />
    </svg>
  );
}

function ToastItem({
  toast,
  onDismiss,
}: {
  toast: Toast;
  onDismiss: (id: string) => void;
}) {
  const styles = variantClasses(toast.variant);
  const isAlert = toast.variant === "error" || toast.variant === "warning";
  return (
    <div
      role={isAlert ? "alert" : "status"}
      aria-live={isAlert ? "assertive" : "polite"}
      className={`pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-md border px-3 py-2.5 backdrop-blur transition-all duration-200 ${styles.container}`}
    >
      <ToastIcon d={styles.iconPath} />
      <div className="min-w-0 flex-1">
        <p className="text-caption font-medium leading-snug">{toast.message}</p>
        {toast.description ? (
          <p className="mt-0.5 text-caption leading-snug opacity-85">{toast.description}</p>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss notification"
        className="rounded text-caption opacity-70 hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-current"
      >
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M6 6 18 18M6 18 18 6" />
        </svg>
      </button>
    </div>
  );
}

function ToastStack({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}) {
  return (
    <div
      aria-label="Notifications"
      className="pointer-events-none fixed inset-x-0 top-4 z-[60] flex flex-col items-center gap-2 px-4 sm:items-end sm:px-6"
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ConfirmDialog({
  state,
  onResolve,
}: {
  state: ConfirmInput;
  onResolve: (ok: boolean) => void;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const variant = state.variant ?? "default";

  useEffect(() => {
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onResolve(false);
      }
      if (e.key === "Tab") {
        const focusables = [cancelRef.current, confirmRef.current].filter(
          (n): n is HTMLButtonElement => Boolean(n),
        );
        if (focusables.length < 2) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        const active = document.activeElement;
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onResolve]);

  const confirmClasses =
    variant === "danger"
      ? "bg-destructive text-white hover:opacity-90 focus-visible:ring-destructive"
      : "bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:ring-ring";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
      aria-describedby={state.description ? "confirm-desc" : undefined}
      className="fixed inset-0 z-[70] flex items-end justify-center bg-black/50 p-4 sm:items-center"
    >
      <div
        className="w-full max-w-md rounded-lg border border-input bg-popover/90 p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="confirm-title" className="text-h5 text-foreground">
          {state.title}
        </h2>
        {state.description ? (
          <p id="confirm-desc" className="mt-2 text-caption leading-relaxed text-muted-foreground">
            {state.description}
          </p>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={() => onResolve(false)}
            className="rounded-md border border-input px-3 py-1.5 text-caption text-muted-foreground transition-colors duration-150 hover:bg-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            {state.cancelLabel ?? "Cancel"}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={() => onResolve(true)}
            className={`rounded-md px-3 py-1.5 text-caption font-medium transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-background ${confirmClasses}`}
          >
            {state.confirmLabel ?? "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}

function PromptDialog({
  state,
  onResolve,
}: {
  state: PromptInput;
  onResolve: (value: string | null) => void;
}) {
  const [value, setValue] = useState(state.defaultValue ?? "");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const id = window.setTimeout(() => inputRef.current?.select(), 0);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onResolve(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(id);
      window.removeEventListener("keydown", onKey);
    };
  }, [onResolve]);

  const submit = () => {
    const trimmed = value.trim();
    if (state.required && !trimmed) return;
    onResolve(trimmed || (state.required ? "" : value));
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="prompt-title"
      className="fixed inset-0 z-[70] flex items-end justify-center bg-black/50 p-4 sm:items-center"
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="w-full max-w-md rounded-lg border border-input bg-popover/90 p-5 shadow-lg"
      >
        <h2 id="prompt-title" className="text-h5 text-foreground">
          {state.title}
        </h2>
        {state.description ? (
          <p className="mt-1 text-caption leading-relaxed text-muted-foreground">{state.description}</p>
        ) : null}
        <label className="mt-4 block text-caption text-muted-foreground">
          {state.label ?? "Value"}
          <input
            ref={inputRef}
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={state.placeholder}
            maxLength={state.maxLength}
            className="mt-1 w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-p text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </label>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => onResolve(null)}
            className="rounded-md border border-input px-3 py-1.5 text-caption text-muted-foreground transition-colors duration-150 hover:bg-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            {state.cancelLabel ?? "Cancel"}
          </button>
          <button
            type="submit"
            disabled={state.required && !value.trim()}
            className="rounded-md bg-primary px-3 py-1.5 text-caption font-medium text-primary-foreground transition-colors duration-150 hover:bg-primary/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-50"
          >
            {state.confirmLabel ?? "OK"}
          </button>
        </div>
      </form>
    </div>
  );
}

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [confirmState, setConfirmState] = useState<
    (ConfirmInput & { resolve: (ok: boolean) => void }) | null
  >(null);
  const [promptState, setPromptState] = useState<
    (PromptInput & { resolve: (value: string | null) => void }) | null
  >(null);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback<FeedbackContextValue["toast"]>(
    (opts) => {
      const id = `t-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const variant = opts.variant ?? "info";
      const next: Toast = {
        id,
        message: opts.message,
        description: opts.description,
        variant,
      };
      setToasts((prev) => [...prev, next].slice(-MAX_TOASTS));
      window.setTimeout(() => dismiss(id), opts.durationMs ?? DEFAULT_DURATION_MS);
    },
    [dismiss],
  );

  const confirm = useCallback<FeedbackContextValue["confirm"]>((opts) => {
    return new Promise<boolean>((resolve) => {
      setConfirmState({ ...opts, resolve });
    });
  }, []);

  const prompt = useCallback<FeedbackContextValue["prompt"]>((opts) => {
    return new Promise<string | null>((resolve) => {
      setPromptState({ ...opts, resolve });
    });
  }, []);

  const value = useMemo<FeedbackContextValue>(
    () => ({ toast, confirm, prompt }),
    [toast, confirm, prompt],
  );

  const resolveConfirm = (ok: boolean) => {
    if (!confirmState) return;
    confirmState.resolve(ok);
    setConfirmState(null);
  };

  const resolvePrompt = (val: string | null) => {
    if (!promptState) return;
    promptState.resolve(val);
    setPromptState(null);
  };

  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <ToastStack toasts={toasts} onDismiss={dismiss} />
      {confirmState ? <ConfirmDialog state={confirmState} onResolve={resolveConfirm} /> : null}
      {promptState ? <PromptDialog state={promptState} onResolve={resolvePrompt} /> : null}
    </FeedbackContext.Provider>
  );
}

export function useFeedback(): FeedbackContextValue {
  const ctx = useContext(FeedbackContext);
  if (!ctx) throw new Error("useFeedback must be used inside <FeedbackProvider>");
  return ctx;
}

export function useToast() {
  return useFeedback().toast;
}

export function useConfirm() {
  return useFeedback().confirm;
}

export function usePrompt() {
  return useFeedback().prompt;
}
