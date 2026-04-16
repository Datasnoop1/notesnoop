"use client";

import { Suspense, useState, useCallback, useRef, useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  searchCompanies,
  searchPeople,
  getFavourites,
  addFavourite,
  removeFavourite,
  getPeopleFavourites,
  addPeopleFavourite,
  removePeopleFavourite,
} from "@/lib/api";
import type { SearchResult, PersonResult } from "@/lib/api";
import { fmtEur, fmtCbe, fmtPct } from "@/lib/format";
import { useTranslation } from "@/components/language-provider";
import { Search, Building, Users, Loader2, Star } from "lucide-react";

export default function UnifiedSearchPage() {
  return (
    <Suspense fallback={<div className="py-8 text-center text-sm text-slate-400">Loading...</div>}>
      <UnifiedSearchPageInner />
    </Suspense>
  );
}

function UnifiedSearchPageInner() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const initialQ = searchParams.get("q") ?? "";
  const [query, setQuery] = useState(initialQ);
  const [companies, setCompanies] = useState<SearchResult[]>([]);
  const [people, setPeople] = useState<PersonResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Favourite state
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
      if (isFav) next.delete(cbe); else next.add(cbe);
      return next;
    });
    (isFav ? removeFavourite(cbe) : addFavourite(cbe)).catch(() => {
      // rollback on failure
      setFavCompanies((prev) => {
        const next = new Set(prev);
        if (isFav) next.add(cbe); else next.delete(cbe);
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
      if (isFav) next.delete(name); else next.add(name);
      return next;
    });
    (isFav ? removePeopleFavourite(name) : addPeopleFavourite(name)).catch(() => {
      setFavPeople((prev) => {
        const next = new Set(prev);
        if (isFav) next.add(name); else next.delete(name);
        return next;
      });
    });
  };

  const doSearch = useCallback((q: string) => {
    setQuery(q);
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (q.trim().length < 2) {
      setCompanies([]);
      setPeople([]);
      setSearched(false);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      setSearched(true);
      try {
        const [c, p] = await Promise.all([
          searchCompanies(q.trim()).catch(() => []),
          searchPeople(q.trim()).catch(() => []),
        ]);
        setCompanies(c);
        setPeople(p);
      } finally {
        setLoading(false);
      }
    }, 300);
  }, []);

  useEffect(() => {
    if (initialQ.trim().length >= 2) doSearch(initialQ);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
            className="pl-12 h-12 text-base rounded-xl border-slate-200 shadow-sm focus:ring-2 focus:ring-indigo-200"
            autoFocus
          />
          {loading && (
            <Loader2 className="absolute right-4 top-1/2 -translate-y-1/2 h-5 w-5 text-indigo-400 animate-spin" />
          )}
        </div>
        {!searched && (
          <p className="text-center text-xs text-slate-400 mt-3">
            {t("search.hint")}
          </p>
        )}
      </div>

      {/* Results */}
      {searched && (
        <div className="space-y-8">

          {/* Top Results — best matches from both */}
          {(companies.length > 0 || people.length > 0) && (
            <div>
              <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2 mb-3">
                {t("search.topResults")}
              </h2>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {/* Top companies */}
                {companies.slice(0, 5).map((c) => (
                  <Link
                    key={`top-${c.enterprise_number}`}
                    href={`/company/${c.enterprise_number}`}
                    className="flex items-center gap-3 px-4 py-3 min-h-[44px] rounded-xl bg-white border border-slate-200 hover:border-indigo-200 hover:shadow-md transition-all group"
                  >
                    <div className="p-2 rounded-lg bg-indigo-50 text-indigo-500 shrink-0">
                      <Building className="w-4 h-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold text-slate-800 group-hover:text-indigo-600 truncate">
                        {c.name || fmtCbe(c.enterprise_number)}
                      </div>
                      <div className="text-[11px] text-slate-400 truncate">
                        {fmtCbe(c.enterprise_number)}
                        {c.city && <span> · {c.city}</span>}
                      </div>
                    </div>
                    {c.revenue != null && (
                      <div className="text-right shrink-0">
                        <div className="text-xs font-mono text-slate-600">{fmtEur(c.revenue)}</div>
                        {c.ebitda_margin_pct != null && (
                          <div className={`text-[10px] font-mono ${c.ebitda_margin_pct >= 15 ? "text-emerald-500" : c.ebitda_margin_pct >= 5 ? "text-amber-500" : "text-rose-400"}`}>
                            {fmtPct(c.ebitda_margin_pct)}
                          </div>
                        )}
                      </div>
                    )}
                    <button
                      onClick={(e) => toggleCompanyFav(c.enterprise_number, e)}
                      className="p-1 rounded-md hover:bg-slate-100 transition-colors shrink-0"
                    >
                      <Star className={`w-3.5 h-3.5 ${favCompanies.has(c.enterprise_number) ? "fill-amber-400 text-amber-400" : "text-slate-300 hover:text-slate-400"}`} />
                    </button>
                  </Link>
                ))}
                {/* Top people */}
                {people.slice(0, 5).map((p, i) => (
                  <Link
                    key={`top-p-${i}`}
                    href={`/people?q=${encodeURIComponent(p.name)}`}
                    className="flex items-center gap-3 px-4 py-3 min-h-[44px] rounded-xl bg-white border border-slate-200 hover:border-emerald-200 hover:shadow-md transition-all group"
                  >
                    <div className="p-2 rounded-lg bg-emerald-50 text-emerald-500 shrink-0">
                      <Users className="w-4 h-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold text-slate-800 group-hover:text-emerald-600 truncate">
                        {p.name}
                      </div>
                      <div className="text-[11px] text-slate-400 truncate">
                        {p.roles > 0 && <span>{p.roles} roles</span>}
                        {p.roles > 0 && p.holdings > 0 && <span> · </span>}
                        {p.holdings > 0 && <span>{p.holdings} holdings</span>}
                      </div>
                    </div>
                    <Badge variant="secondary" className="text-[10px] shrink-0">
                      {p.companies} {p.companies === 1 ? "co." : "cos."}
                    </Badge>
                    <button
                      onClick={(e) => togglePersonFav(p.name, e)}
                      className="p-1 rounded-md hover:bg-slate-100 transition-colors shrink-0"
                    >
                      <Star className={`w-3.5 h-3.5 ${favPeople.has(p.name) ? "fill-amber-400 text-amber-400" : "text-slate-300 hover:text-slate-400"}`} />
                    </button>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {/* Full Companies list */}
          {companies.length > 5 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Building className="w-4 h-4 text-indigo-500" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                  {t("search.allCompanies")}
                </h2>
                <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                  {companies.length}
                </Badge>
              </div>
              <div className="space-y-0.5">
                {companies.slice(5).map((c) => (
                  <Link
                    key={c.enterprise_number}
                    href={`/company/${c.enterprise_number}`}
                    className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-white hover:shadow-sm border border-transparent hover:border-slate-200 transition-all group"
                  >
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-slate-800 group-hover:text-indigo-600 truncate">
                        {c.name || fmtCbe(c.enterprise_number)}
                      </div>
                      <div className="text-[11px] text-slate-400 mt-0.5 truncate">
                        {fmtCbe(c.enterprise_number)}
                        {c.city && <span> · {c.city}</span>}
                        {c.sector && <span> · {c.sector}</span>}
                      </div>
                    </div>
                    <div className="text-right shrink-0 ml-3">
                      {c.revenue != null && (
                        <div className="text-xs font-mono text-slate-600">{fmtEur(c.revenue)}</div>
                      )}
                    </div>
                    <button
                      onClick={(e) => toggleCompanyFav(c.enterprise_number, e)}
                      className="p-1 rounded-md hover:bg-slate-100 transition-colors shrink-0"
                    >
                      <Star className={`w-3.5 h-3.5 ${favCompanies.has(c.enterprise_number) ? "fill-amber-400 text-amber-400" : "text-slate-300 hover:text-slate-400"}`} />
                    </button>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {/* Full People list */}
          {people.length > 5 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Users className="w-4 h-4 text-emerald-500" />
                <h2 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                  {t("search.allPeople")}
                </h2>
                <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                  {people.length}
                </Badge>
              </div>
              <div className="space-y-0.5">
                {people.slice(5).map((p, i) => (
                  <Link
                    key={`all-p-${i}`}
                    href={`/people?q=${encodeURIComponent(p.name)}`}
                    className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-white hover:shadow-sm border border-transparent hover:border-slate-200 transition-all group"
                  >
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-slate-800 group-hover:text-emerald-600 truncate">
                        {p.name}
                      </div>
                      <div className="text-[11px] text-slate-400 mt-0.5">
                        {p.roles > 0 && <span>{p.roles} roles</span>}
                        {p.roles > 0 && p.holdings > 0 && <span> · </span>}
                        {p.holdings > 0 && <span>{p.holdings} holdings</span>}
                      </div>
                    </div>
                    <Badge variant="secondary" className="text-[10px] shrink-0">
                      {p.companies} cos.
                    </Badge>
                    <button
                      onClick={(e) => togglePersonFav(p.name, e)}
                      className="p-1 rounded-md hover:bg-slate-100 transition-colors shrink-0"
                    >
                      <Star className={`w-3.5 h-3.5 ${favPeople.has(p.name) ? "fill-amber-400 text-amber-400" : "text-slate-300 hover:text-slate-400"}`} />
                    </button>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {/* No results */}
          {companies.length === 0 && people.length === 0 && !loading && (
            <div className="rounded-lg border border-dashed border-slate-200 p-8 text-center">
              <p className="text-sm text-slate-400">{t("search.noResults", { query })}</p>
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!searched && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl mx-auto mt-4">
          <Link href="/company">
            <div className="rounded-xl border border-slate-200 p-5 hover:shadow-md hover:border-indigo-200 transition-all cursor-pointer group text-center">
              <Building className="w-8 h-8 text-indigo-400 mx-auto mb-2 group-hover:text-indigo-600 transition-colors" />
              <h3 className="text-sm font-semibold text-slate-700">{t("search.browseCompanies")}</h3>
              <p className="text-[11px] text-slate-400 mt-1">{t("search.browseCompaniesDesc")}</p>
            </div>
          </Link>
          <Link href="/people">
            <div className="rounded-xl border border-slate-200 p-5 hover:shadow-md hover:border-emerald-200 transition-all cursor-pointer group text-center">
              <Users className="w-8 h-8 text-emerald-400 mx-auto mb-2 group-hover:text-emerald-600 transition-colors" />
              <h3 className="text-sm font-semibold text-slate-700">{t("search.browsePeople")}</h3>
              <p className="text-[11px] text-slate-400 mt-1">{t("search.browsePeopleDesc")}</p>
            </div>
          </Link>
        </div>
      )}
    </div>
  );
}
