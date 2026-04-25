"use client";

/**
 * HeaderSearch — grouped autocomplete combobox for the top nav.
 *
 * Implements the WAI-ARIA 1.2 combobox pattern:
 *   - role="combobox" on the input, aria-expanded on open
 *   - aria-controls → dropdown listbox id
 *   - aria-activedescendant → highlighted option id
 *   - ↑/↓ move selection across flattened option list
 *   - Enter opens the highlighted item OR navigates to /search?q=… if none
 *   - Escape closes; Tab closes and moves focus on
 *
 * Data: /api/search/suggest returns `{companies, people, cbe_match,
 * addresses}`. We debounce keystrokes to 150ms and cancel in-flight
 * requests with AbortController.
 */

import { Search, Building, Users, MapPin, Hash } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type {
  SuggestAddress,
  SuggestCbeMatch,
  SuggestCompany,
  SuggestPerson,
  SuggestResponse,
} from "@/lib/api";
import { suggestSearch } from "@/lib/api";

type FlatOption =
  | { kind: "company"; index: number; data: SuggestCompany }
  | { kind: "person"; index: number; data: SuggestPerson }
  | { kind: "cbe"; index: number; data: SuggestCbeMatch }
  | { kind: "address"; index: number; data: SuggestAddress };

function buildOptions(r: SuggestResponse | null): FlatOption[] {
  if (!r) return [];
  const out: FlatOption[] = [];
  r.companies.forEach((c, i) => out.push({ kind: "company", index: i, data: c }));
  r.people.forEach((p, i) => out.push({ kind: "person", index: i, data: p }));
  if (r.cbe_match) out.push({ kind: "cbe", index: 0, data: r.cbe_match });
  r.addresses.forEach((a, i) => out.push({ kind: "address", index: i, data: a }));
  return out;
}

function optionHref(opt: FlatOption, fallbackQuery: string): string {
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

export default function HeaderSearch() {
  const router = useRouter();
  const listboxId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SuggestResponse | null>(null);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState<number>(-1);

  const options = useMemo(() => buildOptions(results), [results]);

  // Debounced fetch.
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (abortRef.current) abortRef.current.abort();
    const q = query.trim();
    if (q.length < 2) {
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
          setActiveIdx(-1);
        }
      } catch {
        // Network/abort — leave state as-is.
      }
    }, 150);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  // Click-outside → close dropdown.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const submit = useCallback(
    (explicit?: FlatOption) => {
      const opt = explicit ?? (activeIdx >= 0 ? options[activeIdx] : undefined);
      const q = query.trim();
      if (opt) {
        router.push(optionHref(opt, q));
        setOpen(false);
        setQuery("");
        setResults(null);
        return;
      }
      if (q.length >= 2) {
        router.push(`/search?q=${encodeURIComponent(q)}`);
        setOpen(false);
        setQuery("");
      }
    },
    [activeIdx, options, query, router],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open && options.length) setOpen(true);
      setActiveIdx((i) => (options.length === 0 ? -1 : (i + 1) % options.length));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) =>
        options.length === 0 ? -1 : (i - 1 + options.length) % options.length,
      );
    } else if (e.key === "Enter") {
      e.preventDefault();
      submit();
    } else if (e.key === "Escape") {
      setOpen(false);
      setActiveIdx(-1);
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  };

  const activeId = activeIdx >= 0 ? `${listboxId}-opt-${activeIdx}` : undefined;

  return (
    <div ref={rootRef} className="relative flex-1 mx-3 sm:mx-4 md:mx-6 max-w-md">
      <div className="group relative flex items-center rounded-full border border-gray-200 bg-white hover:border-gray-300 focus-within:border-gray-400 focus-within:shadow-[0_1px_6px_rgba(32,33,36,0.1)] transition-all">
        <Search
          className="absolute left-3 w-3.5 h-3.5 text-gray-400 pointer-events-none"
          aria-hidden
        />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            if (options.length > 0) setOpen(true);
          }}
          onKeyDown={onKeyDown}
          placeholder="Search"
          aria-label="Search companies, people, or addresses"
          role="combobox"
          aria-expanded={open && options.length > 0}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          className="w-full h-11 md:h-9 pl-9 pr-3 text-base md:text-[13px] rounded-full bg-transparent focus:outline-none placeholder:text-gray-400 text-gray-900"
          enterKeyHint="search"
          autoCapitalize="off"
          autoCorrect="off"
        />
      </div>

      {open && results && options.length > 0 && (
        <ul
          id={listboxId}
          role="listbox"
          className="absolute left-0 right-0 top-full mt-1 z-50 bg-white rounded-lg shadow-lg border border-slate-200 max-h-[70vh] overflow-y-auto py-1"
        >
          {results.companies.length > 0 && (
            <GroupHeader icon={Building} label="Companies" />
          )}
          {results.companies.map((c, i) => {
            const flatIdx = i;
            return (
              <Option
                key={`c-${c.cbe}`}
                id={`${listboxId}-opt-${flatIdx}`}
                active={activeIdx === flatIdx}
                onMouseEnter={() => setActiveIdx(flatIdx)}
                onClick={() => submit({ kind: "company", index: i, data: c })}
                primary={c.name}
                secondary={[c.city, c.category !== "commercial" ? c.category : null]
                  .filter(Boolean)
                  .join(" · ")}
                icon={Building}
                tone={c.category === "commercial" ? "primary" : "muted"}
              />
            );
          })}

          {results.people.length > 0 && (
            <GroupHeader icon={Users} label="People" />
          )}
          {results.people.map((p, i) => {
            const flatIdx = results.companies.length + i;
            return (
              <Option
                key={`p-${p.name}`}
                id={`${listboxId}-opt-${flatIdx}`}
                active={activeIdx === flatIdx}
                onMouseEnter={() => setActiveIdx(flatIdx)}
                onClick={() => submit({ kind: "person", index: i, data: p })}
                primary={p.name}
                secondary={`${p.company_count} ${p.company_count === 1 ? "co." : "cos."}`}
                icon={Users}
                tone="emerald"
              />
            );
          })}

          {results.cbe_match && (
            <>
              <GroupHeader icon={Hash} label="Enterprise number" />
              <Option
                id={`${listboxId}-opt-${results.companies.length + results.people.length}`}
                active={activeIdx === results.companies.length + results.people.length}
                onMouseEnter={() =>
                  setActiveIdx(results.companies.length + results.people.length)
                }
                onClick={() =>
                  submit({ kind: "cbe", index: 0, data: results.cbe_match! })
                }
                primary={results.cbe_match.name}
                secondary={results.cbe_match.cbe}
                icon={Hash}
                tone="primary"
              />
            </>
          )}

          {results.addresses.length > 0 && (
            <GroupHeader icon={MapPin} label="Addresses" />
          )}
          {results.addresses.map((a, i) => {
            const baseIdx =
              results.companies.length +
              results.people.length +
              (results.cbe_match ? 1 : 0);
            const flatIdx = baseIdx + i;
            return (
              <Option
                key={`a-${a.cbe}-${i}`}
                id={`${listboxId}-opt-${flatIdx}`}
                active={activeIdx === flatIdx}
                onMouseEnter={() => setActiveIdx(flatIdx)}
                onClick={() => submit({ kind: "address", index: i, data: a })}
                primary={a.street ?? a.city ?? a.zipcode ?? "—"}
                secondary={[a.zipcode, a.city].filter(Boolean).join(" ")}
                icon={MapPin}
                tone="muted"
              />
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Local primitives
// ---------------------------------------------------------------------------

function GroupHeader({
  icon: Icon,
  label,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
}) {
  return (
    <li
      aria-hidden
      className="flex items-center gap-1.5 px-3 pt-2 pb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400"
    >
      <Icon className="w-3 h-3" />
      {label}
    </li>
  );
}

function Option({
  id,
  active,
  onMouseEnter,
  onClick,
  primary,
  secondary,
  icon: Icon,
  tone,
}: {
  id: string;
  active: boolean;
  onMouseEnter: () => void;
  onClick: () => void;
  primary: string;
  secondary: string;
  icon: React.ComponentType<{ className?: string }>;
  tone: "primary" | "emerald" | "muted";
}) {
  const tint =
    tone === "primary"
      ? "text-brand"
      : tone === "emerald"
        ? "text-emerald-500"
        : "text-slate-400";
  return (
    <li
      id={id}
      role="option"
      aria-selected={active}
      onMouseEnter={onMouseEnter}
      onMouseDown={(e) => {
        // mousedown fires before the input's blur; prevents the
        // click-outside handler from closing the list first.
        e.preventDefault();
        onClick();
      }}
      className={`flex items-center gap-2 px-3 py-2 cursor-pointer text-[13px] ${
        active ? "bg-slate-100" : "hover:bg-slate-50"
      }`}
    >
      <Icon className={`w-3.5 h-3.5 shrink-0 ${tint}`} />
      <span className="font-medium text-slate-800 truncate">{primary}</span>
      {secondary && (
        <span className="text-slate-400 text-[11px] truncate ml-auto">{secondary}</span>
      )}
    </li>
  );
}
