"use client";

/**
 * useInstantSearch — shared autocomplete state for the Google-style
 * instant-search behaviour (top-result auto-highlight + inline ghost
 * text). Used by both the header search bar and the landing-page hero
 * input so the two surfaces stay in sync.
 *
 * Owns: debounced /api/search/suggest fetch, abort cancellation, the
 * flattened option list, the active option index, and the ghost-text
 * suffix derived from a strict case-insensitive prefix match against
 * `companies[0].name`.
 *
 * Does NOT own: rendering, routing, click-outside dismissal — those
 * stay with each consumer because the visual styling and target route
 * differ between surfaces.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  SuggestAddress,
  SuggestCbeMatch,
  SuggestCompany,
  SuggestPerson,
  SuggestResponse,
} from "@/lib/api";
import { suggestSearch } from "@/lib/api";

export type FlatOption =
  | { kind: "company"; index: number; data: SuggestCompany }
  | { kind: "person"; index: number; data: SuggestPerson }
  | { kind: "cbe"; index: number; data: SuggestCbeMatch }
  | { kind: "address"; index: number; data: SuggestAddress };

export function buildOptions(r: SuggestResponse | null): FlatOption[] {
  if (!r) return [];
  const out: FlatOption[] = [];
  r.companies.forEach((c, i) => out.push({ kind: "company", index: i, data: c }));
  r.people.forEach((p, i) => out.push({ kind: "person", index: i, data: p }));
  if (r.cbe_match) out.push({ kind: "cbe", index: 0, data: r.cbe_match });
  r.addresses.forEach((a, i) => out.push({ kind: "address", index: i, data: a }));
  return out;
}

export function optionHref(opt: FlatOption, fallbackQuery: string): string {
  switch (opt.kind) {
    case "company":
      return `/company/${opt.data.cbe}`;
    case "person":
      return `/people?q=${encodeURIComponent(opt.data.name)}`;
    case "cbe":
      return `/company/${opt.data.cbe}`;
    case "address":
      return `/search?q=${encodeURIComponent(fallbackQuery)}`;
  }
}

export interface UseInstantSearchOpts {
  /** Debounce window in ms before firing /api/search/suggest. */
  debounceMs?: number;
  /** Minimum query length before fetching. */
  minLength?: number;
}

export function useInstantSearch(opts: UseInstantSearchOpts = {}) {
  const { debounceMs = 150, minLength = 2 } = opts;
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SuggestResponse | null>(null);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState<number>(-1);

  const options = useMemo(() => buildOptions(results), [results]);

  const ghostSuffix = useMemo(() => {
    const q = query;
    if (!q) return "";
    const top = results?.companies?.[0]?.name;
    if (!top) return "";
    if (top.length > q.length && top.toLowerCase().startsWith(q.toLowerCase())) {
      return top.slice(q.length);
    }
    return "";
  }, [query, results]);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (abortRef.current) abortRef.current.abort();
    const q = query.trim();
    if (q.length < minLength) {
      setResults(null);
      setActiveIdx(-1);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      const ac = new AbortController();
      abortRef.current = ac;
      try {
        const r = await suggestSearch(q, ac.signal);
        if (!ac.signal.aborted) {
          setResults(r);
          const opts2 = buildOptions(r);
          setActiveIdx(opts2.length > 0 ? 0 : -1);
        }
      } catch {
        // Network / abort — leave state as-is.
      }
    }, debounceMs);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      if (abortRef.current) abortRef.current.abort();
    };
  }, [query, debounceMs, minLength]);

  const acceptGhost = useCallback(() => {
    const top = results?.companies?.[0]?.name;
    if (!top || !ghostSuffix) return false;
    setQuery(top);
    return true;
  }, [ghostSuffix, results]);

  const reset = useCallback(() => {
    setQuery("");
    setResults(null);
    setOpen(false);
    setActiveIdx(-1);
  }, []);

  return {
    query,
    setQuery,
    results,
    options,
    activeIdx,
    setActiveIdx,
    open,
    setOpen,
    ghostSuffix,
    acceptGhost,
    reset,
  };
}
