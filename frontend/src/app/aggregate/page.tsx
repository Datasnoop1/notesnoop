"use client";

import React, { useState, useCallback, useRef, useEffect, useMemo } from "react";
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
  loadCompanyNBB,
  getFavouriteProjects,
  getCompanyStructure,
} from "@/lib/api";
import type { SearchResult, FinancialYear, FavouriteProject } from "@/lib/api";
import { fmtEur, fmtCbe, fmtPct, fmtNumber } from "@/lib/format";
import {
  Search,
  X,
  Plus,
  Download,
  Layers,
  Loader2,
  Star,
  Building2,
  FolderOpen,
  ChevronDown,
} from "lucide-react";
import FavouritesDialog from "@/components/favourites-dialog";
import { useTranslation } from "@/components/language-provider";

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

/** Structured P&L lines matching the company profile style */
interface AggPnlLine {
  label: string;
  metric: AggMetricDef;
  bold?: boolean;
  topBorder?: boolean;
  doubleBorder?: boolean;
  section?: string;
  indent?: boolean;
  isKeyMetric?: boolean;
}

const COST_OF_SALES_METRIC: AggMetricDef = {
  label: "Cost of Sales",
  key: "net_debt", // reused key, derive overrides
  format: "eur",
  derive: (r) => {
    if (r.revenue == null || r.gross_margin == null) return null;
    return -(r.revenue - r.gross_margin);
  },
};
const GROSS_PROFIT_METRIC: AggMetricDef = { label: "Gross Profit", key: "gross_margin" as keyof FinancialYear, format: "eur" };
const PERSONNEL_METRIC: AggMetricDef = {
  label: "Personnel Costs",
  key: "personnel_costs",
  format: "eur",
  derive: (r) => (r.personnel_costs != null ? -Math.abs(r.personnel_costs) : null),
};
const DA_METRIC: AggMetricDef = {
  label: "D&A",
  key: "da" as keyof FinancialYear,
  format: "eur",
  derive: (r) => (r.da != null ? -Math.abs(r.da) : null),
};
const OTHER_OP_METRIC: AggMetricDef = {
  label: "Other Operating Costs",
  key: "net_debt",
  format: "eur",
  derive: (r) => {
    const gm = r.gross_margin;
    const ebit = r.ebit;
    if (gm == null || ebit == null) return null;
    const v = -(gm - ebit - Math.abs(r.personnel_costs ?? 0) - Math.abs(r.da ?? 0));
    return Math.abs(v) > 0.5 ? v : null;
  },
};
const FIN_CHARGES_METRIC: AggMetricDef = {
  label: "Financial Charges",
  key: "financial_charges" as keyof FinancialYear,
  format: "eur",
  derive: (r) => (r.financial_charges != null ? -Math.abs(r.financial_charges) : null),
};
const PBT_METRIC: AggMetricDef = {
  label: "Profit Before Tax",
  key: "net_debt",
  format: "eur",
  derive: (r) => {
    if (r.ebit == null || r.financial_charges == null) return null;
    return r.ebit - Math.abs(r.financial_charges);
  },
};
const EBITDA_MARGIN_METRIC: AggMetricDef = {
  label: "EBITDA Margin",
  key: "ebitda_margin_pct",
  format: "pct",
  isRatio: true,
  ratioNum: "ebitda",
  ratioDen: "revenue",
};

const PNL_LINES: AggPnlLine[] = [
  { label: "Revenue", metric: { label: "Revenue", key: "revenue", format: "eur" }, section: "REVENUE" },
  { label: "Cost of Sales", metric: COST_OF_SALES_METRIC, indent: true },
  { label: "Gross Profit", metric: GROSS_PROFIT_METRIC, bold: true, topBorder: true },
  { label: "Personnel Costs", metric: PERSONNEL_METRIC, section: "OPERATING COSTS", indent: true },
  { label: "Depreciation & Amortization", metric: DA_METRIC, indent: true },
  { label: "Other Operating Costs", metric: OTHER_OP_METRIC, indent: true },
  { label: "EBIT (Operating Profit)", metric: { label: "EBIT", key: "ebit", format: "eur" }, bold: true, topBorder: true, isKeyMetric: true },
  { label: "Financial Charges", metric: FIN_CHARGES_METRIC, section: "FINANCIAL", indent: true },
  { label: "Profit Before Tax", metric: PBT_METRIC, bold: true, topBorder: true, isKeyMetric: true },
  { label: "Net Profit", metric: { label: "Net Profit", key: "net_profit", format: "eur" }, bold: true, doubleBorder: true, isKeyMetric: true },
  { label: "EBITDA", metric: { label: "EBITDA", key: "ebitda", format: "eur" }, bold: true, section: "EBITDA", topBorder: true, isKeyMetric: true },
  { label: "EBITDA Margin", metric: EBITDA_MARGIN_METRIC },
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

/** Format a value in accounting style for aggregated P&L */
function fmtAggAcct(
  v: number | null,
  isCost = false,
  isKeyMetric = false
): React.ReactNode {
  if (v == null) return <span className="text-slate-300">{"\u2014"}</span>;
  if (isCost && v < 0) {
    return <span className="text-slate-500">({fmtEur(Math.abs(v))})</span>;
  }
  if (isKeyMetric && v < 0) {
    return <span className="text-rose-400">({fmtEur(Math.abs(v))})</span>;
  }
  if (v < 0) {
    return <span className="text-slate-500">({fmtEur(Math.abs(v))})</span>;
  }
  return <>{fmtEur(v)}</>;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function AggregatePage() {
  const { t } = useTranslation();
  const [companies, setCompanies] = useState<AggCompany[]>([]);
  /* Pre-suggested group/subsidiary candidates pulled from
     participating_interest links of any already-added company. Light
     touch: chips appear below the input; user can add or ignore. */
  const [groupSuggestions, setGroupSuggestions] = useState<{ cbe: string; name: string }[]>([]);
  const groupSuggestSeen = React.useRef<Set<string>>(new Set());
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
    return Array.from(yearSet).sort((a, b) => a - b);
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
        let finData = await getCompanyFinancials(cbe);

        // Auto-load from NBB if no financials
        if (!finData.summary || finData.summary.length === 0) {
          try {
            const loadResult = await loadCompanyNBB(cbe);
            if (loadResult.rubrics_loaded > 0) {
              finData = await getCompanyFinancials(cbe);
            }
          } catch {
            // NBB load failed — continue with no data
          }
        }

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

      // Lazy-fetch group suggestions from this company's participating
      // interests. Cached per primary CBE so adding & removing the same
      // company doesn't refetch. Failure is silent — pure UX nicety.
      if (!groupSuggestSeen.current.has(cbe)) {
        groupSuggestSeen.current.add(cbe);
        getCompanyStructure(cbe)
          .then((struct) => {
            const seen = new Set<string>();
            const newOnes: { cbe: string; name: string }[] = [];
            for (const pi of struct.participating_interests ?? []) {
              const candidate = (pi as { identifier?: string | null }).identifier?.replace?.(/\D/g, "");
              if (candidate && candidate.length === 10 && !seen.has(candidate)) {
                seen.add(candidate);
                newOnes.push({
                  cbe: candidate,
                  name: (pi as { name?: string | null }).name || candidate,
                });
              }
              if (newOnes.length >= 6) break;
            }
            if (newOnes.length > 0) {
              setGroupSuggestions((prev) => {
                const existing = new Set(prev.map((s) => s.cbe));
                const merged = [...prev];
                for (const item of newOnes) {
                  if (!existing.has(item.cbe)) {
                    merged.push(item);
                  }
                }
                return merged.slice(0, 12);
              });
            }
          })
          .catch(() => {
            // Non-critical
          });
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

  // ── Load from project ───────────────────────────────────────
  const [projects, setProjects] = useState<FavouriteProject[]>([]);
  const [showProjectMenu, setShowProjectMenu] = useState(false);
  const [loadingProject, setLoadingProject] = useState(false);
  const projectMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (showProjectMenu) {
      getFavouriteProjects()
        .then(setProjects)
        .catch(() => setProjects([]));
    }
  }, [showProjectMenu]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (projectMenuRef.current && !projectMenuRef.current.contains(e.target as Node)) {
        setShowProjectMenu(false);
      }
    }
    if (showProjectMenu) {
      document.addEventListener("mousedown", handleClick);
      return () => document.removeEventListener("mousedown", handleClick);
    }
  }, [showProjectMenu]);

  const loadProject = useCallback(
    async (project: FavouriteProject) => {
      setShowProjectMenu(false);
      setLoadingProject(true);
      try {
        const existing = new Set(companies.map((c) => c.cbe));
        const toAdd = project.members
          .filter((m) => !existing.has(m.enterprise_number))
          .slice(0, MAX_COMPANIES - companies.length);

        for (const m of toAdd) {
          await addCompany(m.enterprise_number, m.name || m.enterprise_number);
        }
      } finally {
        setLoadingProject(false);
      }
    },
    [companies, addCompany]
  );

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
    <div className="mx-auto w-full max-w-[1200px] space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">
          <Layers className="w-5 h-5 inline mr-2 -mt-0.5 text-slate-400" />
          {t("aggregate.title")}
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          {t("aggregate.subtitle", { max: String(MAX_COMPANIES) })}
        </p>
      </div>

      {/* Search bar + favourites button */}
      <div className="flex flex-wrap gap-2 items-start">
        <div className="relative flex-1 min-w-0 sm:min-w-[280px] max-w-md" ref={searchRef}>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input
              placeholder={t("aggregate.searchPlaceholder")}
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
                  {t("aggregate.noCompaniesFound")}
                </p>
              </div>
            )}
        </div>

        {/* Quick actions */}
        <div className="flex flex-wrap gap-2 items-center">
          <FavouritesDialog
            existingCbes={existingCbes}
            onAdd={addCompany}
            max={MAX_COMPANIES}
          />
          <Button
            variant="outline"
            size="sm"
            className="py-2.5"
            onClick={loadAllFavourites}
            disabled={loadingFavs || companies.length >= MAX_COMPANIES}
          >
            {loadingFavs ? (
              <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
            ) : (
              <Star className="h-4 w-4 mr-1.5 text-amber-500 fill-amber-500" />
            )}
            <span className="hidden sm:inline">{t("aggregate.loadAllFavourites")}</span>
            <span className="sm:hidden">{t("aggregate.allFavs")}</span>
          </Button>
          <div className="relative" ref={projectMenuRef}>
            <Button
              variant="outline"
              size="sm"
              className="py-2.5"
              onClick={() => setShowProjectMenu((p) => !p)}
              disabled={loadingProject || companies.length >= MAX_COMPANIES}
            >
              {loadingProject ? (
                <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
              ) : (
                <FolderOpen className="h-4 w-4 mr-1.5 text-indigo-500" />
              )}
              <span className="hidden sm:inline">{t("aggregate.loadProject")}</span>
              <span className="sm:hidden">{t("aggregate.project")}</span>
              <ChevronDown className="h-3 w-3 ml-1 text-slate-400" />
            </Button>
            {showProjectMenu && (
              <div className="absolute z-50 mt-1 right-0 sm:left-0 w-64 bg-white border border-slate-200 rounded-lg shadow-lg overflow-hidden">
                <div className="px-3 py-2 border-b border-slate-100 bg-slate-50">
                  <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider">
                    {t("aggregate.yourProjects")}
                  </span>
                </div>
                {projects.length === 0 ? (
                  <p className="text-xs text-slate-400 p-4 text-center">
                    {t("aggregate.noProjectsYet")}
                  </p>
                ) : (
                  <div className="max-h-56 overflow-y-auto">
                    {projects.map((p) => (
                      <button
                        key={p.id}
                        onClick={() => loadProject(p)}
                        disabled={p.members.length === 0}
                        className="w-full text-left px-3 py-2.5 hover:bg-indigo-50 border-b border-slate-50 last:border-0 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        <span className="text-sm font-medium text-slate-800 block truncate">
                          {p.name}
                        </span>
                        <span className="text-[10px] text-slate-400">
                          {p.members.length}{" "}
                          {p.members.length === 1 ? "company" : "companies"}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {companies.length >= MAX_COMPANIES && (
          <span className="text-xs text-slate-400 self-center">
            {t("aggregate.maxReached", { max: String(MAX_COMPANIES) })}
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
                className="ml-0.5 hover:bg-indigo-100 rounded-full p-1.5 -mr-1 transition-colors"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Group suggestions — companies linked via participating-interest
          to any of the already-added companies. Light touch: chips only,
          one click to add (or one click to add ALL), dismissible. */}
      {(() => {
        const existingSet = new Set(companies.map((c) => c.cbe));
        const visible = groupSuggestions.filter((s) => !existingSet.has(s.cbe));
        if (visible.length === 0) return null;
        const room = MAX_COMPANIES - companies.length;
        const addAllCount = Math.min(visible.length, room);
        return (
          <div className="flex flex-wrap items-center gap-2 text-[12px]">
            <span className="text-slate-400 font-medium uppercase tracking-wider text-[10px]">
              {t("aggregate.suggestedFromGroup")}
            </span>
            {visible.map((s) => (
              <button
                key={s.cbe}
                onClick={() => addCompany(s.cbe, s.name)}
                disabled={companies.length >= MAX_COMPANIES}
                className="inline-flex items-center gap-1 rounded-full border border-dashed border-indigo-200 bg-white px-2.5 py-1 text-[11px] font-medium text-indigo-700 hover:border-indigo-400 hover:bg-indigo-50 disabled:opacity-40"
                title={t("aggregate.suggestionTooltip", { name: s.name })}
              >
                <Plus className="h-3 w-3" />
                <span className="max-w-[160px] truncate">{s.name}</span>
              </button>
            ))}
            {addAllCount > 1 && (
              <button
                onClick={async () => {
                  for (const s of visible.slice(0, room)) {
                    await addCompany(s.cbe, s.name);
                  }
                }}
                className="inline-flex items-center gap-1 rounded-full bg-indigo-600 text-white px-2.5 py-1 text-[11px] font-medium hover:bg-indigo-700"
                title={t("aggregate.addAllN", { count: String(addAllCount) })}
              >
                {t("aggregate.addAllN", { count: String(addAllCount) })}
              </button>
            )}
            <button
              onClick={() => setGroupSuggestions([])}
              className="text-slate-400 hover:text-slate-600 ml-1 text-[10px]"
              title={t("aggregate.dismissSuggestions")}
            >
              {t("aggregate.dismissSuggestions")}
            </button>
          </div>
        );
      })()}

      {/* KPI Summary (text lines per company) */}
      {companies.length >= 1 && !anyLoading && (
        <div className="space-y-1.5">
          {companies.map((c) => {
            const latest = c.allYears.length > 0 ? c.allYears[c.allYears.length - 1] : null;
            if (!latest) return null;
            const margin = latest.revenue && latest.ebitda ? (latest.ebitda / latest.revenue) * 100 : null;
            return (
              <div key={`kpi-${c.cbe}`} className="text-xs text-slate-600">
                <Link href={`/company/${c.cbe}`} className="font-semibold text-indigo-600 hover:underline">
                  {c.name}
                </Link>
                <span className="text-slate-300 mx-1.5">|</span>
                <span className="text-slate-500">{t("aggregate.rev")}</span>{" "}
                <span className="font-mono font-medium text-slate-800">{fmtEur(latest.revenue)}</span>
                <span className="text-slate-300 mx-1.5">|</span>
                <span className="text-slate-500">EBITDA</span>{" "}
                <span className="font-mono font-medium text-slate-800">{fmtEur(latest.ebitda)}</span>
                <span className="text-slate-300 mx-1.5">|</span>
                <span className="text-slate-500">{t("aggregate.margin")}</span>{" "}
                <span className={`font-mono font-medium ${
                  margin != null
                    ? margin >= 15 ? "text-emerald-600" : margin >= 5 ? "text-amber-600" : "text-rose-400"
                    : "text-slate-300"
                }`}>{margin != null ? `${margin.toFixed(1)}%` : "\u2014"}</span>
                <span className="text-slate-300 mx-1.5">|</span>
                <span className="text-slate-500">{t("aggregate.netProfit")}</span>{" "}
                <span className={`font-mono font-medium ${(latest.net_profit ?? 0) < 0 ? "text-rose-400" : "text-slate-800"}`}>
                  {fmtEur(latest.net_profit)}
                </span>
                <span className="text-slate-300 mx-1.5">|</span>
                <span className="text-slate-500">FTE</span>{" "}
                <span className="font-mono font-medium text-slate-800">
                  {latest.fte_total != null ? fmtNumber(latest.fte_total) : "\u2014"}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Aggregated P&L table (matches company profile style) */}
      {companies.length >= 1 && allYears.length > 0 && !anyLoading && (
        <>
          <div>
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2">
              {t("aggregate.aggregatedIncomeStatement")}
            </h3>
            <div className="rounded-lg border overflow-x-auto bg-white">
              <table className="w-full">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200">
                    <th className="sticky left-0 z-10 bg-slate-50 px-2 md:px-4 py-2 text-left text-[11px] md:text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[120px] md:w-auto md:min-w-[220px] shadow-[1px_0_0_rgba(226,232,240,1)]">
                      {t("aggregate.lineItem")}
                    </th>
                    {allYears.map((year) => (
                      <th key={year} className="px-2 md:px-3 py-2 text-right text-[11px] md:text-[10px] font-medium text-slate-400 uppercase tracking-wider min-w-[80px] md:min-w-[110px]">
                        FY{year}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    let lastSection = "";
                    return PNL_LINES.map((line) => {
                      const showSection = line.section && line.section !== lastSection;
                      if (line.section) lastSection = line.section;
                      const isCost = line.indent && !line.bold;
                      return (
                        <React.Fragment key={line.label}>
                          {showSection && (
                            <tr>
                              <td colSpan={allYears.length + 1} className="sticky left-0 bg-white px-4 pt-3 pb-1">
                                <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest">{line.section}</span>
                              </td>
                            </tr>
                          )}
                          <tr className={`${line.topBorder ? "border-t border-slate-200" : ""} ${line.doubleBorder ? "border-t-2 border-slate-400" : ""}`}>
                            <td className={`sticky left-0 z-[5] bg-white px-2 md:px-4 py-1 text-[11px] md:text-xs whitespace-normal break-words w-[120px] md:w-auto shadow-[1px_0_0_rgba(226,232,240,1)] ${line.bold ? "font-bold text-slate-800" : "text-slate-600"} ${line.indent ? "pl-4 md:pl-8" : ""}`}>
                              {line.label}
                            </td>
                            {allYears.map((year) => {
                              const val = sumMetric(companies, year, line.metric);
                              if (line.metric.format === "pct") {
                                return (
                                  <td key={year} className={`px-2 md:px-3 py-1 text-right text-[11px] md:text-xs font-mono ${line.bold ? "font-bold" : ""}`}>
                                    {val != null ? (
                                      <span className={val >= 15 ? "text-emerald-600" : val >= 5 ? "text-amber-600" : "text-rose-400"}>
                                        {val.toFixed(1)}%
                                      </span>
                                    ) : (
                                      <span className="text-slate-300">{"\u2014"}</span>
                                    )}
                                  </td>
                                );
                              }
                              return (
                                <td key={year} className={`px-2 md:px-3 py-1 text-right text-[11px] md:text-xs font-mono ${line.bold ? "font-bold" : ""}`}>
                                  {fmtAggAcct(val, isCost, line.isKeyMetric)}
                                </td>
                              );
                            })}
                          </tr>
                        </React.Fragment>
                      );
                    });
                  })()}
                  {/* FTE row */}
                  <tr className="border-t border-slate-200">
                    <td className="px-4 py-1 text-xs text-slate-600">FTE</td>
                    {allYears.map((year) => {
                      const val = sumMetric(companies, year, METRICS.find((m) => m.key === "fte_total")!);
                      return (
                        <td key={year} className="px-3 py-1 text-right text-xs font-mono">
                          {val != null ? fmtNumber(val) : <span className="text-slate-300">{"\u2014"}</span>}
                        </td>
                      );
                    })}
                  </tr>
                  {/* Companies w/ data row */}
                  <tr className="border-t-2 border-slate-200">
                    <td className="px-4 py-1 text-xs text-slate-500 italic">
                      {t("aggregate.companiesWithData")}
                    </td>
                    {allYears.map((year) => {
                      const count = companies.filter((c) =>
                        c.allYears.some((fy) => fy.fiscal_year === year)
                      ).length;
                      return (
                        <td key={year} className="px-3 py-1 text-right text-[10px] text-slate-400 tabular-nums">
                          {count} / {companies.length}
                        </td>
                      );
                    })}
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="mt-1 text-[10px] text-slate-400 italic">
              {t("compare.pnlNote")}
            </p>
          </div>

          {/* Per-company breakdown */}
          <details className="group">
            <summary className="cursor-pointer text-sm text-indigo-600 font-medium hover:text-indigo-800 select-none flex items-center gap-1.5">
              <Building2 className="h-3.5 w-3.5 text-slate-400" />
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
              {t("aggregate.exportCsv")}
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
            {t("aggregate.emptySearch")}
          </p>
          <p className="text-xs text-slate-400 mt-1">
            {t("aggregate.emptyHint")}
          </p>
        </div>
      )}
    </div>
  );
}
