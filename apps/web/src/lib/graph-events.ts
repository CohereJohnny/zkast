"use client";

import { useEffect } from "react";

const EVENT_NAME = "zkast:graph-invalidated";

/**
 * Fire when something has changed the working graph from outside the canvas
 * (document deletes, ingestion completion, etc.) so listeners can refetch.
 *
 * Safe to call on the server — it's a no-op when `window` is undefined.
 */
export function emitGraphInvalidated(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(EVENT_NAME));
}

/** Subscribe to graph-invalidation events for the lifetime of the calling component. */
export function useGraphInvalidated(handler: () => void): void {
  useEffect(() => {
    if (typeof window === "undefined") return;
    const fn = () => handler();
    window.addEventListener(EVENT_NAME, fn);
    return () => window.removeEventListener(EVENT_NAME, fn);
  }, [handler]);
}
