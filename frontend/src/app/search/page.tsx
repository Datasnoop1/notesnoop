"use client";

import { Suspense, useState, useCallback, useRef, useEffect, useDeferredValue } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Input } from "@/components/ui/input";
import {
  searchCompaniesBucketed,
  searchPeople,
  searchEvents,
  getFavourites,
  addFavourite,
  removeFavourite,
  getPeopleFavourites,
  addPeopleFavourite,
  removePeopleFavourite,
} from "@/lib/api";
import type {
  CompanySearchResponseV2,
  PersonResult,
  StaatsbladEvent,
} from "@/lib/api";
import { useTranslation } from "@/components/language-provider";
import { Search, Building, Users, Loader2, Landmark, MapPin, X as XIcon } from "lucide-react";
import {
  CommercialSection,
  PeopleSection,
  NonprofitSection,
  EventsSection,
  SectionSkeleton,
} from "./_components/sections";

export default function UnifiedSearchPage() {
  return (
    <Suspense
      fallback={<div className="py-8 text-center text-sm text-slate-400">Loading...</div>}
    >
      <UnifiedSearchPageInner />
    </Suspense>
  );
}

function UnifiedSearchPageInner() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const initialQ = searchParams.get("q") ?? "";
  const initialPostal = searchParams.get("postal_code") ?? "";
  const initialMuni = searchParams.get("municipality") ?? "";
  const initialStreet = searchParams.get("street") ?? "";
  const [query, setQuery] = useState(initialQ);

  // Location filters (#6). They scope the company search only — people and
  // events stay unfiltered because that's how the operator expects them.
  const [locPostalCode, setLocPostalCode] = useState(initialPostal);
  const [locMunicipality, setLocMunicipality] = useState(initialMuni);
  const [locStreet, setLocStreet] = useState(initialStreet);
  const [locFiltersOpen, setLocFiltersOpen] = useState(
    !!(initialPostal || initialMuni || initialStreet),
  );

  // New bucketed response: { commercial, nonprofit_or_public, total }.
  const [companies, setCompanies] = useState<CompanySearchResponseV2 | null>(null);
  const [people, setPeople] = useState<PersonResult[]>([]);
  const [events, setEvents] = useState<StaatsbladEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Favourite state — loaded once, mutated optimistically.
  const [favCompanies, setFavCompanies] = useState<Set<string>>(new Set());
  const [favPeople, setFavPeople] = useState<Set<string>>(new Set());

  useEffect(() => {
    getFavourites()
      .then((items) => setFavCompanies(new Set(items.map((f) => f.enterprise_number))))
      .catch(() => {});
    getPeopleFavourites()
      .then((items) => setFavPeople(new Set(items.map((f) => f.person_name))))
      .catch(() => {});
  }, []);

  // useCallback so the result section components can React.memo
  // without their props' identity changing on every keystroke. Without
  // this, every character typed re-renders all 30+ result cards.
  const toggleCompanyFav = useCallback((cbe: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setFavCompanies((prev) => {
      const isFav = prev.has(cbe);
      const next = new Set(prev);
      if (isFav) next.delete(cbe);
      else next.add(cbe);
      (isFav ? removeFavourite(cbe) : addFavourite(cbe)).catch(() => {
        setFavCompanies((p) => {
          const r = new Set(p);
          if (isFav) r.add(cbe);
          else r.delete(cbe);
          return r;
        });
      });
      return next;
    });
  }, []);

  const togglePersonFav = useCallback((name: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setFavPeople((prev) => {
      const isFav = prev.has(name);
      const next = new Set(prev);
      if (isFav) next.delete(name);
      else next.add(name);
      (isFav ? removePeopleFavourite(name) : addPeopleFavourite(name)).catch(() => {
        setFavPeople((p) => {
          const r = new Set(p);
          if (isFav) r.add(name);
          else r.delete(name);
          return r;
        });
      });
      return next;
    });
  }, []);

  const doSearch = useCallback((q: string, loc?: { postalCode: string; municipality: string; street: string }) => {
    setQuery(q);
    // URL sync without triggering a navigation — smooth back button.
    if (typeof window !== "undefined") {
      const sp = new URLSearchParams(window.location.search);
      if (q.trim()) sp.set("q", q.trim());
      else sp.delete("q");
      const setOrDel = (k: string, v: string | undefined) => {
        if (v && v.trim()) sp.set(k, v.trim());
        else sp.delete(k);
      };
      setOrDel("postal_code", loc?.postalCode);
      setOrDel("municipality", loc?.municipality);
      setOrDel("street", loc?.street);
      window.history.replaceState({}, "", `/search${sp.toString() ? "?" + sp.toString() : ""}`);
    }

    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (abortRef.current) abortRef.current.abort();

    const trimmed = q.trim();
    const hasLocFilter = !!(
      loc?.postalCode?.trim() ||
      loc?.municipality?.trim() ||
      loc?.street?.trim()
    );

    // Need at least a name term OR a location filter. Empty both → reset.
    if (trimmed.length < 2 && !hasLocFilter) {
      setCompanies(null);
      setPeople([]);
      setEvents([]);
      setSearched(false);
      return;
    }

    // 100ms debounce — feels instant. AbortController cancels stale
    // in-flight requests so rapid typing only commits the final batch.
    debounceRef.current = setTimeout(() => {
      const ac = new AbortController();
      abortRef.current = ac;
      setLoading(true);
      setSearched(true);

      // People + events are not location-filtered today; when a
      // location filter is set we'd be showing them unfiltered which
      // is misleading. Skip them while a location filter is active —
      // operator can clear the location to see people again.
      const includeNameSearches = trimmed.length >= 2 && !hasLocFilter;
      // Events search is disabled on /search — its FTS path scans
      // 200K+ event rows per query (~2-4 s even warm) and the
      // footer-sized output didn't justify the latency. A dedicated
      // events page can re-introduce it with a precomputed tsvector
      // column.
      let remaining = 1; // companies always
      if (includeNameSearches) remaining += 1;
      const done = () => {
        if (--remaining === 0 && !ac.signal.aborted) setLoading(false);
      };

      searchCompaniesBucketed(trimmed, loc, ac.signal)
        .then((c) => { if (!ac.signal.aborted) setCompanies(c); })
        .catch(() => {})
        .finally(done);

      if (includeNameSearches) {
        searchPeople(trimmed, ac.signal)
          .then((p) => { if (!ac.signal.aborted) setPeople(p); })
          .catch(() => {})
          .finally(done);
      } else {
        setPeople([]);
      }

      setEvents([]);
    }, 100);
  }, []);

  useEffect(() => {
    const hasInitialLoc = !!(initialPostal || initialMuni || initialStreet);
    if (initialQ.trim().length >= 2 || hasInitialLoc) {
      doSearch(initialQ, {
        postalCode: initialPostal,
        municipality: initialMuni,
        street: initialStreet,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Location filter changes go through doSearch directly at each input's
  // onChange so they share the 200ms debounce with the main query.

  const commercialList = companies?.commercial ?? [];
  const nonprofitList = companies?.nonprofit_or_public ?? [];
  const commercialTotal = companies?.total?.commercial ?? commercialList.length;
  const nonprofitTotal = companies?.total?.nonprofit_or_public ?? nonprofitList.length;

  // Defer the `query` value passed to memoised result sections. While
  // the user is typing, deferredQuery stays at the previous value, so
  // CommercialSection / PeopleSection (both React.memo) skip re-render
  // until typing settles. Result: keystrokes feel instant even with a
  // large result list visible from the previous search.
  const deferredQuery = useDeferredValue(query);

  const isSearchingEmpty =
    searched &&
    !loading &&
    commercialList.length === 0 &&
    nonprofitList.length === 0 &&
    people.length === 0 &&
    events.length === 0;

  return (
    <div className="space-y-6">
      {/* Search bar — sticky on mobile so the input stays in reach as
          results scroll. Pinned at `top-[108px]` to clear the global
          nav (64px header + ~44px dot-row). z-30 sits above the page
          content but below the nav (z-50), so on scroll the search
          bar lands flush against the nav's lower edge instead of
          sliding underneath it. Disabled on sm+ where there's enough
          room not to need it (`sm:static sm:top-auto`). */}
      <div className="max-w-2xl mx-auto sticky top-[108px] z-30 bg-background/95 backdrop-blur-sm pt-1 pb-2 -mx-4 px-4 sm:mx-0 sm:px-0 sm:static sm:top-auto sm:bg-transparent sm:backdrop-blur-none sm:pt-0 sm:pb-0">
        <div className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-slate-400 pointer-events-none" />
          <Input
            placeholder={t("search.placeholder")}
            value={query}
            onChange={(e) => doSearch(e.target.value)}
            // text-[16px] avoids iOS Safari's auto-zoom on focus.
            className="pl-12 pr-12 h-12 text-[16px] rounded-xl border-slate-200 shadow-sm focus:ring-2 focus:ring-brand/30"
            autoFocus
            aria-label={t("search.placeholder")}
            enterKeyHint="search"
            autoCapitalize="off"
            autoCorrect="off"
          />
          {/* Trailing slot — clear button OR loading spinner. Clear
              gives mobile users a quick way out without reaching for
              the OS keyboard's backspace. */}
          {loading ? (
            <Loader2 className="absolute right-4 top-1/2 -translate-y-1/2 h-5 w-5 text-brand/60 animate-spin pointer-events-none" />
          ) : query ? (
            <button
              type="button"
              onClick={() => doSearch("", { postalCode: locPostalCode, municipality: locMunicipality, street: locStreet })}
              aria-label="Clear search"
              className="absolute right-2 top-1/2 -translate-y-1/2 inline-flex items-center justify-center w-8 h-8 rounded-full text-slate-400 hover:bg-slate-100 active:bg-slate-200 transition-colors"
            >
              <XIcon className="h-4 w-4" />
            </button>
          ) : null}
        </div>
        {!searched && (
          <p className="text-center text-xs text-slate-400 mt-3">{t("search.hint")}</p>
        )}

        {/* Location filter row — collapsible so the default look stays
            clean. Once an operator opens it, the three fields persist
            until they're cleared. Typing debounces through doSearch. */}
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setLocFiltersOpen((prev) => !prev)}
            className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-brand transition-colors"
            aria-expanded={locFiltersOpen}
          >
            <MapPin className="h-3.5 w-3.5" />
            {t("search.location") !== "search.location" ? t("search.location") : "Filter by location"}
            {(locPostalCode || locMunicipality || locStreet) && (
              <span className="ml-1 inline-flex items-center justify-center min-w-[18px] h-[18px] rounded-full bg-brand text-white text-[10px] px-1">
                {[locPostalCode, locMunicipality, locStreet].filter(Boolean).length}
              </span>
            )}
          </button>
          {locFiltersOpen && (
            <div className="mt-2 grid grid-cols-1 md:grid-cols-3 gap-2">
              <Input
                placeholder={t("search.postalCode") !== "search.postalCode" ? t("search.postalCode") : "Postal code"}
                value={locPostalCode}
                onChange={(e) => {
                  setLocPostalCode(e.target.value);
                  doSearch(query, {
                    postalCode: e.target.value,
                    municipality: locMunicipality,
                    street: locStreet,
                  });
                }}
                className="h-10 md:h-9 text-base md:text-sm"
                inputMode="numeric"
                maxLength={10}
              />
              <Input
                placeholder={t("search.municipality") !== "search.municipality" ? t("search.municipality") : "Municipality"}
                value={locMunicipality}
                onChange={(e) => {
                  setLocMunicipality(e.target.value);
                  doSearch(query, {
                    postalCode: locPostalCode,
                    municipality: e.target.value,
                    street: locStreet,
                  });
                }}
                className="h-10 md:h-9 text-base md:text-sm"
              />
              <Input
                placeholder={t("search.street") !== "search.street" ? t("search.street") : "Street"}
                value={locStreet}
                onChange={(e) => {
                  setLocStreet(e.target.value);
                  doSearch(query, {
                    postalCode: locPostalCode,
                    municipality: locMunicipality,
                    street: e.target.value,
                  });
                }}
                className="h-10 md:h-9 text-base md:text-sm"
              />
              {(locPostalCode || locMunicipality || locStreet) && (
                <button
                  type="button"
                  onClick={() => {
                    setLocPostalCode("");
                    setLocMunicipality("");
                    setLocStreet("");
                    doSearch(query, { postalCode: "", municipality: "", street: "" });
                  }}
                  className="md:col-span-3 inline-flex items-center justify-center gap-1 text-[11px] text-slate-500 hover:text-rose-500"
                >
                  <XIcon className="h-3 w-3" /> Clear location filter
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Results */}
      {searched && (
        <div className="space-y-6 sm:space-y-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6">
            {loading && companies === null ? (
              <SectionSkeleton
                icon={Building}
                label={t("search.sections.commercial")}
                accent="indigo"
                rows={5}
              />
            ) : (
              <CommercialSection
                companies={commercialList}
                total={commercialTotal}
                favCompanies={favCompanies}
                onToggleFav={toggleCompanyFav}
                query={deferredQuery}
              />
            )}
            {loading && people.length === 0 ? (
              <SectionSkeleton
                icon={Users}
                label={t("search.sections.people")}
                accent="emerald"
                rows={5}
              />
            ) : (
              <PeopleSection
                people={people}
                favPeople={favPeople}
                onToggleFav={togglePersonFav}
                query={deferredQuery}
              />
            )}
          </div>

          {/* Non-profits & public — demoted, collapsed */}
          <NonprofitSection
            companies={nonprofitList}
            total={nonprofitTotal}
            favCompanies={favCompanies}
            onToggleFav={toggleCompanyFav}
            query={query}
          />

          {/* Events — smallest, at the bottom */}
          <EventsSection events={events} />

          {isSearchingEmpty && (
            <div className="rounded-lg border border-dashed border-slate-200 p-8 text-center">
              <p className="text-sm text-slate-400">{t("search.noResults", { query })}</p>
            </div>
          )}
        </div>
      )}

      {/* Empty-state shortcuts — unchanged from V1 */}
      {!searched && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl mx-auto mt-4">
          <Link href="/company" className="block">
            <div className="rounded-xl border border-slate-200 p-5 hover:shadow-md hover:border-brand/30 transition-all cursor-pointer group text-center">
              <Building className="w-8 h-8 text-brand/60 mx-auto mb-2 group-hover:text-brand transition-colors" />
              <h3 className="text-sm font-semibold text-slate-700">
                {t("search.browseCompanies")}
              </h3>
              <p className="text-[11px] text-slate-400 mt-1">
                {t("search.browseCompaniesDesc")}
              </p>
            </div>
          </Link>
          <Link href="/people" className="block">
            <div className="rounded-xl border border-slate-200 p-5 hover:shadow-md hover:border-emerald-200 transition-all cursor-pointer group text-center">
              <Users className="w-8 h-8 text-emerald-400 mx-auto mb-2 group-hover:text-emerald-600 transition-colors" />
              <h3 className="text-sm font-semibold text-slate-700">
                {t("search.browsePeople")}
              </h3>
              <p className="text-[11px] text-slate-400 mt-1">
                {t("search.browsePeopleDesc")}
              </p>
            </div>
          </Link>
        </div>
      )}
    </div>
  );
}
