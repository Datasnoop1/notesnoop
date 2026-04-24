"use client";

import { Suspense, useState, useCallback, useRef, useEffect } from "react";
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
import { Search, Building, Users, Loader2, Landmark } from "lucide-react";
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
  const [query, setQuery] = useState(initialQ);

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

  const toggleCompanyFav = (cbe: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const isFav = favCompanies.has(cbe);
    setFavCompanies((prev) => {
      const next = new Set(prev);
      if (isFav) next.delete(cbe);
      else next.add(cbe);
      return next;
    });
    (isFav ? removeFavourite(cbe) : addFavourite(cbe)).catch(() => {
      // Rollback on failure.
      setFavCompanies((prev) => {
        const next = new Set(prev);
        if (isFav) next.add(cbe);
        else next.delete(cbe);
        return next;
      });
    });
  };

  const togglePersonFav = (name: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const isFav = favPeople.has(name);
    setFavPeople((prev) => {
      const next = new Set(prev);
      if (isFav) next.delete(name);
      else next.add(name);
      return next;
    });
    (isFav ? removePeopleFavourite(name) : addPeopleFavourite(name)).catch(() => {
      setFavPeople((prev) => {
        const next = new Set(prev);
        if (isFav) next.add(name);
        else next.delete(name);
        return next;
      });
    });
  };

  const doSearch = useCallback((q: string) => {
    setQuery(q);
    // URL sync without triggering a navigation — smooth back button.
    if (typeof window !== "undefined") {
      const sp = new URLSearchParams(window.location.search);
      if (q.trim()) sp.set("q", q.trim());
      else sp.delete("q");
      window.history.replaceState({}, "", `/search${sp.toString() ? "?" + sp.toString() : ""}`);
    }

    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (abortRef.current) abortRef.current.abort();

    if (q.trim().length < 2) {
      setCompanies(null);
      setPeople([]);
      setEvents([]);
      setSearched(false);
      return;
    }

    // 100ms debounce — feels like instant-search-as-you-type. Each
    // keystroke aborts the previous in-flight requests via
    // AbortController, so even if the user types fast we only pay for
    // the last batch. Zero debounce would cost ~8 requests per word;
    // 100ms collapses typical typing bursts into 2-3 requests.
    debounceRef.current = setTimeout(() => {
      const ac = new AbortController();
      abortRef.current = ac;
      setLoading(true);
      setSearched(true);

      // Fire the three calls independently and render each as it
      // returns. Previously we `await Promise.all([...])`, so the
      // slowest call (usually searchEvents, which does a pgvector
      // embedding lookup and can hit OpenRouter on cache miss) blocked
      // companies + people from painting. Now commercial + people
      // typically appear within ~200ms and events fill in later.
      let remaining = 3;
      const done = () => {
        if (--remaining === 0 && !ac.signal.aborted) setLoading(false);
      };

      searchCompaniesBucketed(q.trim())
        .then((c) => { if (!ac.signal.aborted) setCompanies(c); })
        .catch(() => {})
        .finally(done);

      searchPeople(q.trim())
        .then((p) => { if (!ac.signal.aborted) setPeople(p); })
        .catch(() => {})
        .finally(done);

      searchEvents(q.trim(), { limit: 10 })
        .then((ev) => { if (!ac.signal.aborted) setEvents(ev.results || []); })
        .catch(() => { if (!ac.signal.aborted) setEvents([]); })
        .finally(done);
    }, 200);
  }, []);

  useEffect(() => {
    if (initialQ.trim().length >= 2) doSearch(initialQ);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const commercialList = companies?.commercial ?? [];
  const nonprofitList = companies?.nonprofit_or_public ?? [];
  const commercialTotal = companies?.total?.commercial ?? commercialList.length;
  const nonprofitTotal = companies?.total?.nonprofit_or_public ?? nonprofitList.length;

  const isSearchingEmpty =
    searched &&
    !loading &&
    commercialList.length === 0 &&
    nonprofitList.length === 0 &&
    people.length === 0 &&
    events.length === 0;

  return (
    <div className="space-y-6">
      {/* Search bar */}
      <div className="max-w-2xl mx-auto">
        <div className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-slate-400" />
          <Input
            placeholder={t("search.placeholder")}
            value={query}
            onChange={(e) => doSearch(e.target.value)}
            // text-[16px] avoids iOS Safari's auto-zoom on focus.
            className="pl-12 h-12 text-[16px] rounded-xl border-slate-200 shadow-sm focus:ring-2 focus:ring-indigo-200"
            autoFocus
            aria-label={t("search.placeholder")}
          />
          {loading && (
            <Loader2 className="absolute right-4 top-1/2 -translate-y-1/2 h-5 w-5 text-indigo-400 animate-spin" />
          )}
        </div>
        {!searched && (
          <p className="text-center text-xs text-slate-400 mt-3">{t("search.hint")}</p>
        )}
      </div>

      {/* Results */}
      {searched && (
        <div className="space-y-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
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
                query={query}
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
                query={query}
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
          <a href="/company" className="block">
            <div className="rounded-xl border border-slate-200 p-5 hover:shadow-md hover:border-indigo-200 transition-all cursor-pointer group text-center">
              <Building className="w-8 h-8 text-indigo-400 mx-auto mb-2 group-hover:text-indigo-600 transition-colors" />
              <h3 className="text-sm font-semibold text-slate-700">
                {t("search.browseCompanies")}
              </h3>
              <p className="text-[11px] text-slate-400 mt-1">
                {t("search.browseCompaniesDesc")}
              </p>
            </div>
          </a>
          <a href="/people" className="block">
            <div className="rounded-xl border border-slate-200 p-5 hover:shadow-md hover:border-emerald-200 transition-all cursor-pointer group text-center">
              <Users className="w-8 h-8 text-emerald-400 mx-auto mb-2 group-hover:text-emerald-600 transition-colors" />
              <h3 className="text-sm font-semibold text-slate-700">
                {t("search.browsePeople")}
              </h3>
              <p className="text-[11px] text-slate-400 mt-1">
                {t("search.browsePeopleDesc")}
              </p>
            </div>
          </a>
        </div>
      )}
    </div>
  );
}
