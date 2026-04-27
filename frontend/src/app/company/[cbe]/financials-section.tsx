"use client";

/**
 * FinancialsSection — client component that fetches financials after mount.
 *
 * Moves the heavy /financials fetch off the server-side Promise.all so the
 * above-the-fold detail + structure can render in <1 s while financial data
 * streams in afterward.  A 15-second AbortController deadline shows a
 * friendly fallback instead of an indefinite spinner; the user can retry
 * without a timeout from there.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { FinancialsData } from "./types";

const FINANCIALS_TIMEOUT_MS = 15_000;

/* ---------- Skeleton ---------- */

export function FinancialsSkeleton() {
  return (
    <div className="space-y-4 py-4">
      {/* chart stand-in */}
      <div className="h-40 w-full animate-pulse rounded-lg bg-slate-200/80" />
      {/* table rows */}
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex gap-3">
          <div className="h-4 w-16 animate-pulse rounded bg-slate-200/80" />
          <div className="h-4 flex-1 animate-pulse rounded bg-slate-200/80" />
          <div className="h-4 w-24 animate-pulse rounded bg-slate-200/80" />
          <div className="h-4 w-24 animate-pulse rounded bg-slate-200/80" />
        </div>
      ))}
    </div>
  );
}

/* ---------- Timeout fallback ---------- */

function FinancialsTimedOut({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 py-12 text-center text-slate-500">
      <p className="text-sm">
        Financials are taking longer than usual to load.
      </p>
      <Button
        variant="outline"
        size="sm"
        onClick={onRetry}
        className="gap-1.5"
      >
        <RefreshCw className="h-3.5 w-3.5" />
        Retry (no time limit)
      </Button>
    </div>
  );
}

/* ---------- Main component ---------- */

interface FinancialsSectionProps {
  cbe: string;
  /**
   * Callback invoked once financials have loaded successfully. The parent
   * page receives the data and passes it down to the tab components that
   * consume it (PnlTab, BalanceSheetTab, etc.).
   */
  onLoaded: (data: FinancialsData) => void;
  /** If the server side already pre-fetched financials (warm path), pass
   *  them here so we skip the client-side fetch entirely. */
  initialFinancials?: FinancialsData | null;
  /**
   * When false the component runs the fetch silently in the background but
   * renders nothing (no skeleton, no error). Useful when the user is on a
   * non-financial tab — the data loads quietly and the UI updates once they
   * switch to Financials. When true (or omitted) the skeleton / error states
   * are visible.
   */
  visible?: boolean;
}

export function FinancialsSection({
  cbe,
  onLoaded,
  initialFinancials,
  visible = true,
}: FinancialsSectionProps) {
  const [state, setState] = useState<
    "idle" | "loading" | "done" | "timeout" | "error"
  >(initialFinancials ? "done" : "idle");

  // Track the in-flight retry-path AbortController + the mount flag so that
  // unmounting the component while a (timeout-free) retry is in flight
  // cancels the fetch instead of writing state on a dead component.
  const retryAbortRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (retryAbortRef.current) {
        retryAbortRef.current.abort();
        retryAbortRef.current = null;
      }
    };
  }, []);

  const fetchFinancials = useCallback(
    async (skipTimeout: boolean) => {
      // Cancel any previous retry that's still running before starting a new one.
      if (retryAbortRef.current) retryAbortRef.current.abort();
      const controller = new AbortController();
      retryAbortRef.current = controller;
      let timer: ReturnType<typeof setTimeout> | null = null;

      setState("loading");

      if (!skipTimeout) {
        timer = setTimeout(() => {
          controller.abort();
        }, FINANCIALS_TIMEOUT_MS);
      }

      try {
        const res = await fetch(
          `/api/companies/${cbe}/financials`,
          { signal: controller.signal }
        );
        if (timer) clearTimeout(timer);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: FinancialsData = await res.json();
        if (!mountedRef.current) return;
        onLoaded(data);
        setState("done");
      } catch (err: unknown) {
        if (timer) clearTimeout(timer);
        if (!mountedRef.current) return;
        const isAbort =
          err instanceof DOMException && err.name === "AbortError";
        setState(isAbort ? "timeout" : "error");
      } finally {
        if (retryAbortRef.current === controller) {
          retryAbortRef.current = null;
        }
      }
    },
    [cbe, onLoaded]
  );

  // Initial load
  useEffect(() => {
    if (initialFinancials) {
      // Already have data — nothing to fetch
      return;
    }
    let abortCtrl: AbortController | null = null;
    const controller = new AbortController();
    abortCtrl = controller;

    const run = async () => {
      setState("loading");
      let timer: ReturnType<typeof setTimeout> | null = setTimeout(() => {
        controller.abort();
      }, FINANCIALS_TIMEOUT_MS);

      try {
        const res = await fetch(`/api/companies/${cbe}/financials`, {
          signal: controller.signal,
        });
        if (timer) { clearTimeout(timer); timer = null; }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: FinancialsData = await res.json();
        onLoaded(data);
        setState("done");
      } catch (err: unknown) {
        if (timer) { clearTimeout(timer); timer = null; }
        if (controller.signal.aborted) {
          setState("timeout");
        } else {
          setState("error");
        }
      }
    };

    run();
    return () => {
      abortCtrl?.abort();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cbe]);

  const handleRetry = useCallback(() => {
    fetchFinancials(true /* no timeout */);
  }, [fetchFinancials]);

  if (state === "done" || initialFinancials) {
    // Data is in parent state — nothing to render here
    return null;
  }

  // Not visible (user is on a non-financial tab) — fetch runs silently
  if (!visible) return null;

  if (state === "loading" || state === "idle") {
    return <FinancialsSkeleton />;
  }

  if (state === "timeout") {
    return <FinancialsTimedOut onRetry={handleRetry} />;
  }

  // error
  return (
    <div className="flex flex-col items-center gap-3 py-12 text-center text-slate-500">
      <p className="text-sm">Could not load financial data.</p>
      <Button variant="outline" size="sm" onClick={handleRetry} className="gap-1.5">
        <RefreshCw className="h-3.5 w-3.5" />
        Retry
      </Button>
    </div>
  );
}
