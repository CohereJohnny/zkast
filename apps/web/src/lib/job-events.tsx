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

/**
 * Tracks the set of "interesting" arq jobs the workspace is watching so the
 * `JobLogConsole` drawer can subscribe to all of them via one SSE per job.
 *
 * Components like the documents panel and the retry-from-stage handler call
 * `registerActiveJob(jobId, documentId, kind)` whenever they start a new
 * pipeline run. The drawer reads `useActiveJobs()` and opens one
 * `EventSource` per job; jobs are auto-unregistered on `job_completed` /
 * `job_failed`.
 */

export type ActiveJobKind =
  | "document_parse"
  | "generate_atomic_notes"
  | "extract_graph";

export type ActiveJob = {
  jobId: string;
  documentId?: string | null;
  kind?: ActiveJobKind | null;
  startedAt: number;
};

type Ctx = {
  jobs: ActiveJob[];
  registerActiveJob: (
    jobId: string,
    docId?: string | null,
    kind?: ActiveJobKind | null,
  ) => void;
  unregisterActiveJob: (jobId: string) => void;
};

const STORAGE_KEY = "zkast.workspace.activeJobs";
const STORAGE_LIMIT = 12;

const JobEventsContext = createContext<Ctx | null>(null);

function loadFromStorage(): ActiveJob[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (j) =>
          j &&
          typeof j === "object" &&
          typeof (j as Record<string, unknown>).jobId === "string",
      )
      .slice(0, STORAGE_LIMIT) as ActiveJob[];
  } catch {
    return [];
  }
}

function saveToStorage(jobs: ActiveJob[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(jobs.slice(0, STORAGE_LIMIT)),
    );
  } catch {
    /* quota / private mode — non-fatal */
  }
}

export function JobEventsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<ActiveJob[]>([]);
  const initialised = useRef(false);

  useEffect(() => {
    if (initialised.current) return;
    initialised.current = true;
    setJobs(loadFromStorage());
  }, []);

  const registerActiveJob = useCallback<Ctx["registerActiveJob"]>(
    (jobId, docId, kind) => {
      setJobs((prev) => {
        const without = prev.filter((j) => j.jobId !== jobId);
        const next: ActiveJob[] = [
          {
            jobId,
            documentId: docId ?? null,
            kind: kind ?? null,
            startedAt: Date.now(),
          },
          ...without,
        ].slice(0, STORAGE_LIMIT);
        saveToStorage(next);
        return next;
      });
    },
    [],
  );

  const unregisterActiveJob = useCallback<Ctx["unregisterActiveJob"]>(
    (jobId) => {
      setJobs((prev) => {
        const next = prev.filter((j) => j.jobId !== jobId);
        saveToStorage(next);
        return next;
      });
    },
    [],
  );

  const value = useMemo<Ctx>(
    () => ({ jobs, registerActiveJob, unregisterActiveJob }),
    [jobs, registerActiveJob, unregisterActiveJob],
  );

  return (
    <JobEventsContext.Provider value={value}>{children}</JobEventsContext.Provider>
  );
}

export function useJobEvents(): Ctx {
  const ctx = useContext(JobEventsContext);
  if (!ctx) {
    return {
      jobs: [],
      registerActiveJob: () => undefined,
      unregisterActiveJob: () => undefined,
    };
  }
  return ctx;
}

export function useActiveJobs(): ActiveJob[] {
  return useJobEvents().jobs;
}
