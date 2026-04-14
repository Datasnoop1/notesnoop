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
  getCompanyDetail,
  getCompanyFinancials,
} from "@/lib/api";
import type { SearchResult, CompanyDetail, FinancialYear } from "@/lib/api";
import { fmtEur, fmtCbe, fmtPct, fmtNumber } from "@/lib/format";
import { Search, X, Plus, Download, ArrowUpDown, Loader2 } from "lucide-react";
import FavouritesDialog from "@/components/favourites-dialog";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface CompanyColumn {
  cbe: string;
  name: string;
  detail: CompanyDetail | null;
  financials: FinancialYear | null; // latest year
  loading: boolean;
}

interface MetricDef {
  label: string;
  key: keyof FinancialYear | "ebitda_margin_pct" | "net_debt";
  format: "eur" | "pct" | "num";
  derive?: (row: FinancialYear) => number | null;
}

const METRICS: MetricDef[] = [
  { label: "Revenue", key: "revenue", format: "eur" },
  { label: "EBITDA", key: "ebitda", format: "eur" },
  {
    label: "Margin %",
    key: "ebitda_margin_pct",
    format: "pct",
    derive: (r) =>
      r.revenue && r.revenue > 0 && r.ebitda != null
        ? (r.ebitda / r.revenue) * 100
        : null,
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

const MAX_COMPANIES = 5;

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
  fin: FinancialYear | null,
  metric: MetricDef
): number | null {
  if (!fin) return null;
  if (metric.derive) return metric.derive(fin);
  const v = fin[metric.key as keyof FinancialYear];
  return typeof v === "number" ? v : null;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ComparePage() {
  const [companies, setCompanies] = useState<CompanyColumn[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
          // Filter out already-added companies
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

  // Add a company to the comparison
  const addCompany = useCallback(
    async (cbe: string, name: string) => {
      if (companies.length >= MAX_COMPANIES) return;
      if (companies.some((c) => c.cbe === cbe)) return;

      setQuery("");
      setResults([]);
      setShowDropdown(false);

      const entry: CompanyColumn = {
        cbe,
        name,
        detail: null,
        financials: null,
        loading: true,
      };
      setCompanies((prev) => [...prev, entry]);

      try {
        const [detail, finData] = await Promise.all([
          getCompanyDetail(cbe),
          getCompanyFinancials(cbe),
        ]);
        const latest =
          finData.summary.length > 0
            ? finData.summary[finData.summary.length - 1]
            : null;

        setCompanies((prev) =>
          prev.map((c) =>
            c.cbe === cbe
              ? {
                  ...c,
                  detail,
                  name: detail.name || name,
                  financials: latest,
                  loading: false,
                }
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

  // Export to CSV
  const exportCsv = useCallback(() => {
    const header = ["Metric", ...companies.map((c) => c.name)];
    const rows = METRICS.map((m) => [
      m.label,
      ...companies.map((c) => {
        const v = getMetricValue(c.financials, m);
        return v != null ? String(v) : "";
      }),
    ]);
    const csv = [header, ...rows].map((r) => r.join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "company_comparison.csv";
    a.click();
    URL.revokeObjectURL(url);
  }, [companies]);

  const existingCbes = useMemo(
    () => new Set(companies.map((c) => c.cbe)),
    [companies]
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">
          Compare Companies
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Side-by-side financial comparison of up to {MAX_COMPANIES} companies
        </p>
      </div>

      {/* Search bar */}
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
          <div className="absolute z-50 mt-1 w-full max-w-md bg-white border border-slate-200 rounded-lg shadow-lg max-h-64 overflow-y-auto">
            {results.map((r) => (
              <button
                key={r.enterprise_number}
                onClick={() =>
                  addCompany(r.enterprise_number, r.name || r.enterprise_number)
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

          {showDropdown && query.trim().length >= 2 && results.length === 0 && !searching && (
            <div className="absolute z-50 mt-1 w-full bg-white border border-slate-200 rounded-lg shadow-lg p-4">
              <p className="text-sm text-slate-400 text-center">
                No companies found
              </p>
            </div>
          )}
        </div>

        {/* Load from Favourites */}
        <FavouritesDialog
          existingCbes={existingCbes}
          onAdd={addCompany}
          max={MAX_COMPANIES}
        />

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
              {c.loading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : null}
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

      {/* Comparison table */}
      {companies.length >= 2 && (
        <>
          <div className="border border-slate-200 rounded-lg bg-white overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50">
                  <TableHead className="w-40 font-semibold text-slate-700">
                    Metric
                  </TableHead>
                  {companies.map((c) => (
                    <TableHead key={c.cbe} className="text-right min-w-[140px]">
                      <div className="flex flex-col items-end gap-0.5">
                        <Link
                          href={`/company/${c.cbe}`}
                          className="font-semibold text-indigo-600 hover:underline truncate max-w-[180px] block"
                        >
                          {c.name.length > 22
                            ? c.name.slice(0, 22) + "..."
                            : c.name}
                        </Link>
                        {c.financials && (
                          <span className="text-[10px] text-slate-400 font-normal">
                            FY{c.financials.fiscal_year}
                          </span>
                        )}
                      </div>
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
                    {companies.map((c) => {
                      if (c.loading) {
                        return (
                          <TableCell key={c.cbe} className="text-right">
                            <span className="text-slate-300 text-sm">...</span>
                          </TableCell>
                        );
                      }
                      const val = getMetricValue(c.financials, metric);
                      return (
                        <TableCell
                          key={c.cbe}
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
              </TableBody>
            </Table>
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <Button variant="outline" size="sm" onClick={exportCsv}>
              <Download className="h-4 w-4 mr-1.5" />
              Export CSV
            </Button>
          </div>
        </>
      )}

      {/* Empty state */}
      {companies.length === 0 && (
        <div className="border border-dashed border-slate-300 rounded-lg p-12 text-center">
          <ArrowUpDown className="h-8 w-8 text-slate-300 mx-auto mb-3" />
          <p className="text-sm text-slate-500">
            Search and add companies above to start comparing.
          </p>
          <p className="text-xs text-slate-400 mt-1">
            Add at least 2 companies to see a side-by-side comparison.
          </p>
        </div>
      )}

      {companies.length === 1 && (
        <div className="border border-dashed border-slate-300 rounded-lg p-8 text-center">
          <p className="text-sm text-slate-500">
            Add at least one more company to compare.
          </p>
        </div>
      )}
    </div>
  );
}
