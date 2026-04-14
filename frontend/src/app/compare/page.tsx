"use client";

import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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

/** Derived P&L row for a single company */
interface PnlRow {
  fiscal_year: number;
  revenue: number | null;
  costOfSales: number | null;
  grossProfit: number | null;
  personnel: number | null;
  da: number | null;
  otherOpCosts: number | null;
  ebit: number | null;
  finCharges: number | null;
  pbt: number | null;
  tax: number | null;
  netProfit: number | null;
  ebitda: number | null;
  ebitdaMarginPct: number | null;
  // Balance sheet
  totalAssets: number | null;
  equity: number | null;
  ltDebt: number | null;
  stDebt: number | null;
  cash: number | null;
  netDebt: number | null;
  // Ratios
  netDebtEbitda: number | null;
  equityRatio: number | null;
  fte: number | null;
}

const MAX_COMPANIES = 5;

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Derive a full P&L row from a FinancialYear */
function derivePnl(row: FinancialYear): PnlRow {
  const revenue = row.revenue;
  const grossProfit = row.gross_margin;
  const costOfSales =
    revenue != null && grossProfit != null
      ? -(revenue - grossProfit)
      : null;
  const personnel =
    row.personnel_costs != null ? -Math.abs(row.personnel_costs) : null;
  const da = row.da != null ? -Math.abs(row.da) : null;
  const ebit = row.ebit;
  const otherOpCostsRaw =
    grossProfit != null && ebit != null
      ? -(
          grossProfit -
          ebit -
          Math.abs(row.personnel_costs ?? 0) -
          Math.abs(row.da ?? 0)
        )
      : null;
  const otherOpCosts =
    otherOpCostsRaw != null && Math.abs(otherOpCostsRaw) > 0.5
      ? otherOpCostsRaw
      : null;
  const finCharges =
    row.financial_charges != null
      ? -Math.abs(row.financial_charges)
      : null;
  const pbt =
    ebit != null && row.financial_charges != null
      ? ebit - Math.abs(row.financial_charges)
      : null;
  const netProfit = row.net_profit;
  const tax =
    pbt != null && netProfit != null ? -(pbt - netProfit) : null;

  // Balance sheet
  const totalAssets = row.total_assets;
  const equity = row.equity;
  const ltDebt = row.lt_financial_debt ?? null;
  const stDebt = row.st_financial_debt ?? null;
  const cash = row.cash;
  const netDebt =
    ltDebt != null || stDebt != null || cash != null
      ? (ltDebt ?? 0) + (stDebt ?? 0) - (cash ?? 0)
      : null;

  // Ratios
  const netDebtEbitda =
    netDebt != null && row.ebitda != null && row.ebitda !== 0
      ? netDebt / row.ebitda
      : null;
  const equityRatio =
    equity != null && totalAssets != null && totalAssets !== 0
      ? (equity / totalAssets) * 100
      : null;

  return {
    fiscal_year: row.fiscal_year,
    revenue,
    costOfSales,
    grossProfit,
    personnel,
    da,
    otherOpCosts,
    ebit,
    finCharges,
    pbt,
    tax,
    netProfit,
    ebitda: row.ebitda,
    ebitdaMarginPct: row.ebitda_margin_pct,
    totalAssets,
    equity,
    ltDebt,
    stDebt,
    cash,
    netDebt,
    netDebtEbitda,
    equityRatio,
    fte: row.fte_total,
  };
}

/** Format a value in accounting style */
function fmtAcct(
  v: number | null,
  isCost = false,
  isKeyMetric = false
): React.ReactNode {
  if (v == null) return <span className="text-slate-300">{"\u2014"}</span>;
  if (isCost && v < 0) {
    return (
      <span className="text-slate-500">({fmtEur(Math.abs(v))})</span>
    );
  }
  if (isKeyMetric && v < 0) {
    return (
      <span className="text-rose-400">({fmtEur(Math.abs(v))})</span>
    );
  }
  if (v < 0) {
    return (
      <span className="text-slate-500">({fmtEur(Math.abs(v))})</span>
    );
  }
  return <>{fmtEur(v)}</>;
}

/** Line definition for the comparison table */
interface CompareLine {
  label: string;
  key: keyof PnlRow;
  isCost?: boolean;
  isKeyMetric?: boolean;
  bold?: boolean;
  topBorder?: boolean;
  doubleBorder?: boolean;
  section?: string;
  indent?: boolean;
  isPct?: boolean;
  isRatio?: boolean;
}

const INCOME_LINES: CompareLine[] = [
  { label: "Revenue", key: "revenue", section: "REVENUE" },
  {
    label: "Cost of Sales",
    key: "costOfSales",
    isCost: true,
    indent: true,
  },
  {
    label: "Gross Profit",
    key: "grossProfit",
    bold: true,
    topBorder: true,
  },
  {
    label: "Personnel Costs",
    key: "personnel",
    isCost: true,
    section: "OPERATING COSTS",
    indent: true,
  },
  {
    label: "Depreciation & Amortization",
    key: "da",
    isCost: true,
    indent: true,
  },
  {
    label: "Other Operating Costs",
    key: "otherOpCosts",
    isCost: true,
    indent: true,
  },
  {
    label: "EBIT (Operating Profit)",
    key: "ebit",
    bold: true,
    topBorder: true,
    isKeyMetric: true,
  },
  {
    label: "Financial Charges",
    key: "finCharges",
    isCost: true,
    section: "FINANCIAL",
    indent: true,
  },
  {
    label: "Profit Before Tax",
    key: "pbt",
    bold: true,
    topBorder: true,
    isKeyMetric: true,
  },
  { label: "Tax", key: "tax", isCost: true, indent: true },
  {
    label: "Net Profit",
    key: "netProfit",
    bold: true,
    doubleBorder: true,
    isKeyMetric: true,
  },
  {
    label: "EBITDA",
    key: "ebitda",
    bold: true,
    section: "EBITDA",
    topBorder: true,
    isKeyMetric: true,
  },
  { label: "EBITDA Margin", key: "ebitdaMarginPct", isPct: true },
];

const BALANCE_LINES: CompareLine[] = [
  { label: "Total Assets", key: "totalAssets" },
  { label: "Equity", key: "equity", indent: true },
  { label: "Long-term Debt", key: "ltDebt", indent: true },
  { label: "Short-term Debt", key: "stDebt", indent: true },
  { label: "Cash", key: "cash", indent: true },
  {
    label: "Net Debt",
    key: "netDebt",
    bold: true,
    topBorder: true,
    isKeyMetric: true,
  },
];

const RATIO_LINES: CompareLine[] = [
  { label: "Net Debt / EBITDA", key: "netDebtEbitda", isRatio: true },
  { label: "Equity Ratio", key: "equityRatio", isPct: true },
  { label: "EBITDA Margin", key: "ebitdaMarginPct", isPct: true },
  { label: "FTE", key: "fte" },
];

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

  // Derive P&L rows for all companies
  const pnlRows = useMemo(
    () =>
      companies.map((c) => ({
        cbe: c.cbe,
        pnl: c.financials ? derivePnl(c.financials) : null,
      })),
    [companies]
  );

  // Export to CSV
  const exportCsv = useCallback(() => {
    const allLines = [
      ...INCOME_LINES.map((l) => ({ ...l, sectionLabel: "Income Statement" })),
      ...BALANCE_LINES.map((l) => ({ ...l, sectionLabel: "Balance Sheet" })),
      ...RATIO_LINES.map((l) => ({ ...l, sectionLabel: "Key Ratios" })),
    ];
    const header = ["Section", "Line Item", ...companies.map((c) => c.name)];
    const rows = allLines.map((line) => [
      line.sectionLabel,
      line.label,
      ...pnlRows.map((pr) => {
        if (!pr.pnl) return "";
        const v = pr.pnl[line.key];
        if (v == null) return "";
        if (line.isPct) return `${(v as number).toFixed(1)}%`;
        if (line.isRatio) return `${(v as number).toFixed(1)}x`;
        return String(v);
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
  }, [companies, pnlRows]);

  const existingCbes = useMemo(
    () => new Set(companies.map((c) => c.cbe)),
    [companies]
  );

  // Render a section of the table
  const renderSection = (
    title: string,
    lines: CompareLine[],
    borderColor: string
  ) => {
    let lastSection = "";
    return (
      <div>
        <h3 className={`mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] ${borderColor} pl-2`}>
          {title}
        </h3>
        <div className="rounded-lg border overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                <th className="px-4 py-2 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider min-w-[220px]">
                  Line Item
                </th>
                {companies.map((c) => (
                  <th
                    key={c.cbe}
                    className="px-3 py-2 text-right text-[10px] font-medium text-slate-400 uppercase tracking-wider min-w-[120px]"
                  >
                    <div className="flex flex-col items-end gap-0.5">
                      <Link
                        href={`/company/${c.cbe}`}
                        className="font-semibold text-indigo-600 hover:underline truncate max-w-[160px] block text-[11px] normal-case"
                      >
                        {c.name.length > 20
                          ? c.name.slice(0, 20) + "..."
                          : c.name}
                      </Link>
                      {c.financials && (
                        <span className="text-[10px] text-slate-400 font-normal">
                          FY{c.financials.fiscal_year}
                        </span>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {lines.map((line) => {
                const showSection =
                  line.section && line.section !== lastSection;
                if (line.section) lastSection = line.section;
                return (
                  <tr
                    key={line.key}
                    className={`${line.topBorder ? "border-t border-slate-200" : ""} ${line.doubleBorder ? "border-t-2 border-slate-400" : ""}`}
                  >
                    <td
                      className={`px-4 py-1 text-xs ${line.bold ? "font-bold text-slate-800" : "text-slate-600"} ${line.indent ? "pl-8" : ""}`}
                    >
                      {showSection && (
                        <div className="pb-1 pt-2">
                          <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-widest">
                            {line.section}
                          </span>
                        </div>
                      )}
                      {line.label}
                    </td>
                    {companies.map((c, idx) => {
                      if (c.loading) {
                        return (
                          <td
                            key={c.cbe}
                            className="px-3 py-1 text-right text-xs"
                          >
                            <span className="text-slate-300">...</span>
                          </td>
                        );
                      }
                      const pnl = pnlRows[idx]?.pnl;
                      if (!pnl) {
                        return (
                          <td
                            key={c.cbe}
                            className="px-3 py-1 text-right text-xs text-slate-300"
                          >
                            {"\u2014"}
                          </td>
                        );
                      }
                      const val = pnl[line.key] as number | null;
                      if (line.isPct) {
                        return (
                          <td
                            key={c.cbe}
                            className={`px-3 py-1 text-right text-xs font-mono ${line.bold ? "font-bold" : ""}`}
                          >
                            {val != null ? (
                              <span
                                className={
                                  val >= 15
                                    ? "text-emerald-600"
                                    : val >= 5
                                      ? "text-amber-600"
                                      : "text-rose-400"
                                }
                              >
                                {val.toFixed(1)}%
                              </span>
                            ) : (
                              <span className="text-slate-300">
                                {"\u2014"}
                              </span>
                            )}
                          </td>
                        );
                      }
                      if (line.isRatio) {
                        return (
                          <td
                            key={c.cbe}
                            className={`px-3 py-1 text-right text-xs font-mono ${line.bold ? "font-bold" : ""}`}
                          >
                            {val != null ? (
                              <span
                                className={
                                  val > 3
                                    ? "text-rose-400"
                                    : val > 2
                                      ? "text-amber-600"
                                      : "text-emerald-600"
                                }
                              >
                                {val.toFixed(1)}x
                              </span>
                            ) : (
                              <span className="text-slate-300">
                                {"\u2014"}
                              </span>
                            )}
                          </td>
                        );
                      }
                      return (
                        <td
                          key={c.cbe}
                          className={`px-3 py-1 text-right text-xs font-mono ${line.bold ? "font-bold" : ""}`}
                        >
                          {line.key === "fte"
                            ? val != null
                              ? fmtNumber(val)
                              : <span className="text-slate-300">{"\u2014"}</span>
                            : fmtAcct(val, line.isCost, line.isKeyMetric)}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

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
                        <span className="text-xs text-slate-400">
                          {r.city}
                        </span>
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

      {/* Full P&L Comparison */}
      {companies.length >= 2 && (
        <>
          <div className="space-y-6">
            {renderSection(
              "Income Statement",
              INCOME_LINES,
              "border-indigo-500"
            )}
            {renderSection(
              "Balance Sheet",
              BALANCE_LINES,
              "border-emerald-500"
            )}
            {renderSection("Key Ratios", RATIO_LINES, "border-amber-500")}
          </div>

          <p className="text-[10px] text-slate-400 italic">
            Gross Profit = rubric 9900. EBIT = rubric 9901. Net Profit = rubric
            9904. Cost of Sales = Revenue - Gross Profit. Other Op. Costs =
            Gross Profit - Personnel - D&A - EBIT. Costs shown in parentheses.
          </p>

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
