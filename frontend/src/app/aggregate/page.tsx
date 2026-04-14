"use client";

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import {
  searchCompanies,
  getCompanyFinancials,
  getFavourites,
} from "@/lib/api";
import type { SearchResult, FinancialYear } from "@/lib/api";
import { fmtEur, fmtCbe, fmtPct, fmtNumber } from "@/lib/format";
import {
  Search,
  X,
  Plus,
  Download,
  Layers,
  Loader2,
  Star,
} from "lucide-react";
import FavouritesDialog from "@/components/favourites-dialog";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface AggCompany {
  cbe: string;
  name: string;
  allYears: FinancialYear[];
  loading: boolean;
}

interface AggMetricDef {
  label: string;
  key: keyof FinancialYear | "ebitda_margin_pct" | "net_debt";
  format: "eur" | "pct" | "num";
  /** If set, derive the value from a FinancialYear row */
  derive?: (row: FinancialYear) => number | null;
  /** If true, show percentage (derived from sums) instead of summing */
  isRatio?: boolean;
  ratioNum?: keyof FinancialYear;
  ratioDen?: keyof FinancialYear;
}

const METRICS: AggMetricDef[] = [
  { label: "Revenue", key: "revenue", format: "eur" },
  { label: "EBITDA", key: "ebitda", format: "eur" },
  {
    label: "EBITDA Margin %",
    key: "ebitda_margin_pct",
    format: "pct",
    isRatio: true,
    ratioNum: "ebitda",
    ratioDen: "revenue",
  },
  { label: "EBIT", key: "ebit", format: "eur" },
  { label: "Net Profit", key: "net_profit", format: "eur" },
  { label: "Equity", key: "equity", format: "eur" },
  { label: "Total Assets", key: "total_assets", format: "eur" },
  { label: "FTE", key: "fte_total", format: "num" },
  {
    label: "Net Debt",
    key: "net_debt",
    format: "eur",
    derive: (r) => {
      const lt = r.lt_financial_debt ?? 0;
      const st = r.st_financial_debt ?? 0;
      const cash = r.cash ?? 0;
      if (lt === 0 && st === 0 && cash === 0) return null;
      return lt + st - cash;
    },
  },
  { label: "Personnel Costs", key: "personnel_costs", format: "eur" },
];

const MAX_COMPANIES = 10;

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatValue(value: number | null | undefined, format: string): string {
  if (value == null || isNaN(value)) return "\u2014";
  switch (format) {
    case "eur":
      return fmtEur(value);
    case "pct":
      return fmtPct(value);
    case "num":
      return fmtNumber(value);
    default:
      return String(value);
  }
}

function getMetricValue(
  fin: FinancialYear,
  metric: AggMetricDef
): number | null {
  if (metric.derive) return metric.derive(fin);
  const v = fin[metric.key as keyof FinancialYear];
  return typeof v === "number" ? v : null;
}

/** Sum a metric across companies for a given year */
function sumMetric(
  companies: AggCompany[],
  year: number,
  metric: AggMetricDef
): number | null {
  if (metric.isRatio && metric.ratioNum && metric.ratioDen) {
    // For ratios, compute sum(num) / sum(den)
    let totalNum = 0;
    let totalDen = 0;
    let hasAny = false;
    for (const c of companies) {
      const fy = c.allYears.find((y) => y.fiscal_year === year);
      if (!fy) continue;
      const num = fy[metric.ratioNum as keyof FinancialYear];
      const den = fy[metric.ratioDen as keyof FinancialYear];
      if (typeof num === "number" && typeof den === "number" && den > 0) {
        totalNum += num;
        totalDen += den;
        hasAny = true;
      }
    }
    if (!hasAny || totalDen === 0) return null;
    return (totalNum / totalDen) * 100;
  }

  let total = 0;
  let hasAny = false;
  for (const c of companies) {
    const fy = c.allYears.find((y) => y.fiscal_year === year);
    if (!fy) continue;
    const v = getMetricValue(fy, metric);
    if (v != null) {
      total += v;
      hasAny = true;
    }
  }
  return hasAny ? total : null;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function AggregatePage() {
  const [companies, setCompanies] = useState<AggCompany[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Collect all distinct years from all companies
  const allYears = useMemo(() => {
    const yearSet = new Set<number>();
    for (const c of companies) {
      for (const fy of c.allYears) {
        yearSet.add(fy.fiscal_year);
      }
    }
    return Array.from(yearSet).sort((a, b) => b - a);
  }, [companies]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Debounced search
  const handleSearch = useCallback(
    (value: string) => {
      setQuery(value);
      if (debounceRef.current) clearTimeout(debounceRef.current);

      if (value.trim().length < 2) {
        setResults([]);
        setShowDropdown(false);
        return;
      }

      debounceRef.current = setTimeout(async () => {
        setSearching(true);
        try {
          const res = await searchCompanies(value.trim());
          const existing = new Set(companies.map((c) => c.cbe));
          setResults(res.filter((r) => !existing.has(r.enterprise_number)));
          setShowDropdown(true);
        } catch {
          setResults([]);
        } finally {
          setSearching(false);
        }
      }, 300);
    },
    [companies]
  );

  // Add a company
  const addCompany = useCallback(
    async (cbe: string, name: string) => {
      if (companies.length >= MAX_COMPANIES) return;
      if (companies.some((c) => c.cbe === cbe)) return;

      setQuery("");
      setResults([]);
      setShowDropdown(false);

      const entry: AggCompany = { cbe, name, allYears: [], loading: true };
      setCompanies((prev) => [...prev, entry]);

      try {
        const finData = await getCompanyFinancials(cbe);
        setCompanies((prev) =>
          prev.map((c) =>
            c.cbe === cbe
              ? { ...c, allYears: finData.summary, loading: false }
              : c
          )
        );
      } catch {
        setCompanies((prev) =>
          prev.map((c) => (c.cbe === cbe ? { ...c, loading: false } : c))
        );
      }
    },
    [companies]
  );

  // Remove a company
  const removeCompany = useCallback((cbe: string) => {
    setCompanies((prev) => prev.filter((c) => c.cbe !== cbe));
  }, []);

  // Load all favourites
  const [loadingFavs, setLoadingFavs] = useState(false);
  const loadAllFavourites = useCallback(async () => {
    setLoadingFavs(true);
    try {
      const favs = await getFavourites();
      const existing = new Set(companies.map((c) => c.cbe));
      const toAdd = favs
        .filter((f) => !existing.has(f.enterprise_number))
        .slice(0, MAX_COMPANIES - companies.length);

      for (const f of toAdd) {
        await addCompany(
          f.enterprise_number,
          f.name || f.enterprise_number
        );
      }
    } catch {
      // ignore
    } finally {
      setLoadingFavs(false);
    }
  }, [companies, addCompany]);

  // Export to CSV
  const exportCsv = useCallback(() => {
    if (allYears.length === 0) return;
    const header = ["Metric", ...allYears.map((y) => `FY${y}`)];
    const rows = METRICS.map((m) => [
      m.label,
      ...allYears.map((year) => {
        const v = sumMetric(companies, year, m);
        return v != null ? String(Math.round(v * 100) / 100) : "";
      }),
    ]);
    const csv = [header, ...rows].map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "aggregated_portfolio.csv";
    a.click();
    URL.revokeObjectURL(url);
  }, [companies, allYears]);

  const existingCbes = useMemo(
    () => new Set(companies.map((c) => c.cbe)),
    [companies]
  );

  const anyLoading = companies.some((c) => c.loading);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">
          Aggregate Portfolio
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Combined P&L and cash flow for up to {MAX_COMPANIES} companies
        </p>
      </div>

      {/* Search bar + favourites button */}
      <div className="flex flex-wrap gap-2 items-start">
        <div className="relative flex-1 min-w-[280px] max-w-md" ref={searchRef}>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input
              placeholder="Search by company name or CBE number..."
              value={query}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                handleSearch(e.target.value)
              }
              className="pl-9"
              disabled={companies.length >= MAX_COMPANIES}
            />
            {searching && (
              <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 animate-spin" />
            )}
          </div>

          {/* Search dropdown */}
          {showDropdown && results.length > 0 && (
            <div className="absolute z-50 mt-1 w-full bg-white border border-slate-200 rounded-lg shadow-lg max-h-64 overflow-y-auto">
              {results.map((r) => (
                <button
                  key={r.enterprise_number}
                  onClick={() =>
                    addCompany(
                      r.enterprise_number,
                      r.name || r.enterprise_number
                    )
                  }
                  className="w-full text-left px-4 py-2.5 hover:bg-slate-50 border-b border-slate-100 last:border-0 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-sm font-medium text-slate-900">
                        {r.name || r.enterprise_number}
                      </span>
                      <span className="ml-2 text-xs text-slate-400">
                        {fmtCbe(r.enterprise_number)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {r.city && (
                        <span className="text-xs text-slate-400">{r.city}</span>
                      )}
                      {r.revenue != null && (
                        <Badge variant="secondary" className="text-[10px]">
                          {fmtEur(r.revenue)}
                        </Badge>
                      )}
                      <Plus className="h-3.5 w-3.5 text-indigo-500" />
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}

          {showDropdown &&
            query.trim().length >= 2 &&
            results.length === 0 &&
            !searching && (
              <div className="absolute z-50 mt-1 w-full bg-white border border-slate-200 rounded-lg shadow-lg p-4">
                <p className="text-sm text-slate-400 text-center">
                  No companies found
                </p>
              </div>
            )}
        </div>

        {/* Quick actions */}
        <div className="flex gap-2 items-center">
          <FavouritesDialog
            existingCbes={existingCbes}
            onAdd={addCompany}
            max={MAX_COMPANIES}
          />
          <Button
            variant="outline"
            size="sm"
            onClick={loadAllFavourites}
            disabled={loadingFavs || companies.length >= MAX_COMPANIES}
          >
            {loadingFavs ? (
              <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
            ) : (
              <Star className="h-4 w-4 mr-1.5 text-amber-500 fill-amber-500" />
            )}
            Load All Favourites
          </Button>
        </div>

        {companies.length >= MAX_COMPANIES && (
          <span className="text-xs text-slate-400 self-center">
            Maximum {MAX_COMPANIES} companies reached
          </span>
        )}
      </div>

      {/* Selected companies chips */}
      {companies.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {companies.map((c) => (
            <div
              key={c.cbe}
              className="inline-flex items-center gap-1.5 bg-indigo-50 text-indigo-700 px-3 py-1.5 rounded-full text-sm font-medium"
            >
              {c.loading && (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              )}
              <Link
                href={`/company/${c.cbe}`}
                className="hover:underline max-w-[200px] truncate"
              >
                {c.name}
              </Link>
              <span className="text-indigo-400 text-xs">
                {fmtCbe(c.cbe)}
              </span>
              <button
                onClick={() => removeCompany(c.cbe)}
                className="ml-0.5 hover:bg-indigo-100 rounded-full p-0.5 transition-colors"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Aggregated table */}
      {companies.length >= 1 && allYears.length > 0 && !anyLoading && (
        <>
          <div className="border border-slate-200 rounded-lg bg-white overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead className="w-40 font-semibold text-slate-700">
                    Metric
                  </TableHead>
                  {allYears.map((year) => (
                    <TableHead
                      key={year}
                      className="text-right min-w-[120px] font-semibold text-slate-700"
                    >
                      FY{year}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {METRICS.map((metric) => (
                  <TableRow key={metric.key} className="hover:bg-slate-50/50">
                    <TableCell className="font-medium text-slate-700 text-sm">
                      {metric.label}
                    </TableCell>
                    {allYears.map((year) => {
                      const val = sumMetric(companies, year, metric);
                      return (
                        <TableCell
                          key={year}
                          className={`text-right text-sm tabular-nums ${
                            val != null && val < 0
                              ? "text-red-600"
                              : "text-slate-900"
                          }`}
                        >
                          {formatValue(val, metric.format)}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                ))}

                {/* Companies included row */}
                <TableRow className="border-t-2 border-slate-200">
                  <TableCell className="font-medium text-slate-500 text-xs italic">
                    Companies w/ data
                  </TableCell>
                  {allYears.map((year) => {
                    const count = companies.filter((c) =>
                      c.allYears.some((fy) => fy.fiscal_year === year)
                    ).length;
                    return (
                      <TableCell
                        key={year}
                        className="text-right text-xs text-slate-400 tabular-nums"
                      >
                        {count} / {companies.length}
                      </TableCell>
                    );
                  })}
                </TableRow>
              </TableBody>
            </Table>
          </div>

          {/* Per-company breakdown */}
          <details className="group">
            <summary className="cursor-pointer text-sm text-indigo-600 font-medium hover:text-indigo-800 select-none">
              Show per-company breakdown
            </summary>
            <div className="mt-3 border border-slate-200 rounded-lg bg-white overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-slate-50">
                    <TableHead className="w-40 font-semibold text-slate-700">
                      Company
                    </TableHead>
                    <TableHead className="text-right">Year</TableHead>
                    <TableHead className="text-right">Revenue</TableHead>
                    <TableHead className="text-right">EBITDA</TableHead>
                    <TableHead className="text-right">Net Profit</TableHead>
                    <TableHead className="text-right">FTE</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {companies.map((c) => {
                    const latest = c.allYears.length > 0 ? c.allYears[c.allYears.length - 1] : null;
                    return (
                      <TableRow key={c.cbe} className="hover:bg-slate-50/50">
                        <TableCell className="text-sm">
                          <Link
                            href={`/company/${c.cbe}`}
                            className="text-indigo-600 hover:underline font-medium"
                          >
                            {c.name.length > 25
                              ? c.name.slice(0, 25) + "..."
                              : c.name}
                          </Link>
                        </TableCell>
                        <TableCell className="text-right text-xs text-slate-500">
                          {latest ? `FY${latest.fiscal_year}` : "\u2014"}
                        </TableCell>
                        <TableCell className="text-right text-sm tabular-nums">
                          {formatValue(latest?.revenue, "eur")}
                        </TableCell>
                        <TableCell className="text-right text-sm tabular-nums">
                          {formatValue(latest?.ebitda, "eur")}
                        </TableCell>
                        <TableCell className="text-right text-sm tabular-nums">
                          {formatValue(latest?.net_profit, "eur")}
                        </TableCell>
                        <TableCell className="text-right text-sm tabular-nums">
                          {formatValue(latest?.fte_total, "num")}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </details>

          {/* Actions */}
          <div className="flex gap-3">
            <Button variant="outline" size="sm" onClick={exportCsv}>
              <Download className="h-4 w-4 mr-1.5" />
              Export CSV
            </Button>
          </div>
        </>
      )}

      {/* Loading indicator when any company is still fetching */}
      {anyLoading && companies.length > 0 && (
        <div className="border border-dashed border-slate-300 rounded-lg p-8 text-center">
          <Loader2 className="h-6 w-6 text-indigo-400 mx-auto mb-2 animate-spin" />
          <p className="text-sm text-slate-500">
            Loading financial data...
          </p>
        </div>
      )}

      {/* Empty state */}
      {companies.length === 0 && (
        <div className="border border-dashed border-slate-300 rounded-lg p-12 text-center">
          <Layers className="h-8 w-8 text-slate-300 mx-auto mb-3" />
          <p className="text-sm text-slate-500">
            Search and add companies above to see their combined financials.
          </p>
          <p className="text-xs text-slate-400 mt-1">
            Useful for seeing what a portfolio of companies looks like combined.
          </p>
        </div>
      )}
    </div>
  );
}
