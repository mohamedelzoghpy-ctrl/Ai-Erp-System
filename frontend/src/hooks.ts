import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export interface Fetched<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Runs `fn` on mount and whenever `key` changes. Ignores results of superseded calls. */
export function useFetch<T>(fn: () => Promise<T>, key: string): Fetched<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fnRef
      .current()
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/** Tracks a pending async action (button click) and its error. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError((e as Error).message);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);

  return { busy, error, setError, run };
}

export const PAGE_SIZE = 50;

export interface PagedList<T> {
  data: T[] | null;
  total: number;
  page: number;
  pages: number;
  setPage: (p: number) => void;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/** Paginated list: `params` are the filters (a change returns to page 1). */
export function usePagedList<T>(path: string, params: Record<string, string | number | boolean | undefined | null>): PagedList<T> {
  const filterKey = path + JSON.stringify(params);
  const [state, setState] = useState({ key: filterKey, page: 1 });
  const page = state.key === filterKey ? state.page : 1; // filters changed -> first page
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "" && v !== false) sp.set(k, String(v));
  sp.set("limit", String(PAGE_SIZE));
  sp.set("skip", String((page - 1) * PAGE_SIZE));
  const f = useFetch(() => api.getPage<T>(`${path}?${sp.toString()}`), `${filterKey}#${page}`);
  const total = f.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  // If rows were deleted and the page no longer exists, step back.
  useEffect(() => {
    if (f.data && page > pages) setState({ key: filterKey, page: pages });
  }, [f.data, page, pages, filterKey]);
  return {
    data: f.data ? f.data.items : null,
    total,
    page,
    pages,
    setPage: (p) => setState({ key: filterKey, page: Math.min(Math.max(1, p), pages) }),
    error: f.error,
    loading: f.loading,
    reload: f.reload,
  };
}
