"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { searchCompanies } from "@/lib/api";
import { fmtCbe, fmtEur, fmtPct } from "@/lib/format";
import { Search, Building2 } from "lucide-react";

interface SearchResult {
  enterprise_number: string;
  name: string;
  status: string;
  jf_label: string | null;
  city: string | null;
  sector: string | null;
  start_date: string | null;
  revenue: number | null;
  ebitda: number | null;
  ebitda_margin_pct: number | null;
  fte_total: number | null;
  fiscal_year: number | null;
}

export default function CompanySearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doSearch = useCallback(async (q: string) => {
    if (q.trim().length < 2) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const data = await searchCompanies(q.trim());
      setResults(data);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(query), 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, doSearch]);

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-8">
      <div className="mb-5 text-center">
        <Building2 className="mx-auto mb-2 h-8 w-8 text-indigo-600" />
        <h1 className="text-xl font-bold text-slate-900">
          Search for a company
        </h1>
        <p className="mt-1 text-xs text-slate-500">
          Search by company name or CBE number
        </p>
      </div>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <Input
          type="text"
          placeholder="Company name or CBE number..."
          className="h-11 pl-10 text-base"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
        />
      </div>

      {loading && (
        <div className="mt-4 space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="h-14 animate-pulse rounded-lg border bg-slate-50"
            />
          ))}
        </div>
      )}

      {!loading && results.length > 0 && (
        <div className="mt-4 space-y-1.5">
          {results.slice(0, 30).map((r) => (
            <Link
              key={r.enterprise_number}
              href={`/company/${r.enterprise_number}`}
              className="block rounded-lg border px-3 py-2.5 transition-colors hover:border-indigo-300 hover:bg-indigo-50/50"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-900 truncate">
                      {r.name || fmtCbe(r.enterprise_number)}
                    </span>
                    {r.status === "AC" ? (
                      <Badge
                        variant="secondary"
                        className="bg-green-50 text-green-700 border-green-200 text-[10px]"
                      >
                        Active
                      </Badge>
                    ) : (
                      <Badge
                        variant="secondary"
                        className="bg-red-50 text-red-700 border-red-200 text-[10px]"
                      >
                        {r.status}
                      </Badge>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-500">
                    <span>{fmtCbe(r.enterprise_number)}</span>
                    {r.city && <span>{r.city}</span>}
                    {r.sector && (
                      <span className="max-w-[250px] truncate">
                        {r.sector}
                      </span>
                    )}
                  </div>
                </div>
                {r.revenue != null && (
                  <div className="shrink-0 text-right text-xs text-slate-500">
                    <div className="font-mono font-medium text-slate-700">
                      {fmtEur(r.revenue)}
                    </div>
                    <div>
                      {r.ebitda_margin_pct != null
                        ? fmtPct(r.ebitda_margin_pct) + " margin"
                        : ""}
                    </div>
                    {r.fiscal_year && (
                      <div className="text-[10px]">FY {r.fiscal_year}</div>
                    )}
                  </div>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}

      {!loading && query.trim().length >= 2 && results.length === 0 && (
        <div className="mt-6 text-center">
          <p className="text-sm text-slate-500">No companies found</p>
          <p className="mt-1 text-xs text-slate-400">
            Try a different name or CBE number
          </p>
        </div>
      )}
    </div>
  );
}
