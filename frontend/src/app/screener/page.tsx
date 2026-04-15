"use client";

import { useState, useCallback, useEffect, useRef, useMemo } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import { getScreener, getNaceSuggestions } from "@/lib/api";
import type { NaceSuggestion } from "@/lib/api";
import { fmtEur, fmtCbe, fmtPct, fmtNumber } from "@/lib/format";
import {
  Download,
  Search,
  RotateCcw,
  Loader2,
  Tag,
  MapPin,
  ChevronUp,
  ChevronDown,
  TrendingUp,
  Save,
  FolderOpen,
  Trash2,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useTranslation } from "@/components/language-provider";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface ScreenerRow {
  cbe: string;
  name: string;
  nace: string;
  city: string;
  fiscal_year: number | null;
  revenue: number | null;
  ebit: number | null;
  ebitda: number | null;
  margin_pct: number | null;
  net_profit: number | null;
  fte: number | null;
  jf_label: string | null;
  start_date: string | null;
}

interface Filters {
  nace: string;
  zipcode: string;
  province: string;
  rev_min: string;
  rev_max: string;
  ebit_min: string;
  ebit_max: string;
  fte_min: string;
  fte_max: string;
  margin_min: string;
  nd_ebitda_max: string;
  rev_growth_min: string;
  rev_growth_max: string;
  ebitda_growth_min: string;
  ebitda_growth_max: string;
  assets_growth_min: string;
  assets_growth_max: string;
  sort: string;
  limit: string;
}

const DEFAULT_FILTERS: Filters = {
  nace: "",
  zipcode: "",
  province: "",
  rev_min: "",
  rev_max: "",
  ebit_min: "",
  ebit_max: "",
  fte_min: "",
  fte_max: "",
  margin_min: "",
  nd_ebitda_max: "",
  rev_growth_min: "",
  rev_growth_max: "",
  ebitda_growth_min: "",
  ebitda_growth_max: "",
  assets_growth_min: "",
  assets_growth_max: "",
  sort: "revenue_desc",
  limit: "100",
};

const PROVINCES = [
  { label: "Antwerpen", prefix: "2" },
  { label: "Brabant Wallon", prefix: "13" },
  { label: "Brussel", prefix: "1" },
  { label: "Hainaut", prefix: "7" },
  { label: "Li\u00e8ge", prefix: "4" },
  { label: "Limburg", prefix: "35" },
  { label: "Luxembourg", prefix: "6" },
  { label: "Namur", prefix: "5" },
  { label: "Oost-Vlaanderen", prefix: "9" },
  { label: "Vlaams-Brabant", prefix: "3" },
  { label: "West-Vlaanderen", prefix: "8" },
];

type FinancialUnit = "raw" | "K" | "M";

type SortKey =
  | "revenue_desc"
  | "ebit_desc"
  | "ebitda_desc"
  | "fte_desc"
  | "name_asc";

const LIMIT_OPTIONS = ["50", "100", "250", "500"];

interface QuickFilter {
  label: string;
  apply: (f: Filters) => Partial<Filters>;
  isActive: (f: Filters) => boolean;
}

const QUICK_FILTERS: QuickFilter[] = [
  {
    label: "Rev > \u20ac1M",
    apply: (f) => (f.rev_min === "1" ? { rev_min: "" } : { rev_min: "1" }),
    isActive: (f) => f.rev_min === "1",
  },
  {
    label: "Rev > \u20ac10M",
    apply: (f) => (f.rev_min === "10" ? { rev_min: "" } : { rev_min: "10" }),
    isActive: (f) => f.rev_min === "10",
  },
  {
    label: "EBIT > 0",
    apply: (f) => (f.ebit_min === "0" ? { ebit_min: "" } : { ebit_min: "0" }),
    isActive: (f) => f.ebit_min === "0",
  },
  {
    label: "FTE > 50",
    apply: (f) => (f.fte_min === "50" ? { fte_min: "" } : { fte_min: "50" }),
    isActive: (f) => f.fte_min === "50",
  },
  {
    label: "Margin > 15%",
    apply: (f) =>
      f.margin_min === "15" ? { margin_min: "" } : { margin_min: "15" },
    isActive: (f) => f.margin_min === "15",
  },
];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function exportCsv(rows: ScreenerRow[]) {
  const headers = [
    "CBE",
    "Name",
    "Legal Form",
    "Founded",
    "NACE",
    "City",
    "FY",
    "Revenue",
    "EBIT",
    "EBITDA",
    "Margin %",
    "Net Profit",
    "FTE",
  ];
  const csvRows = rows.map((r) =>
    [
      fmtCbe(r.cbe),
      `"${(r.name ?? "").replace(/"/g, '""')}"`,
      `"${(r.jf_label ?? "").replace(/"/g, '""')}"`,
      r.start_date ? r.start_date.slice(0, 4) : "",
      `"${(r.nace ?? "").replace(/"/g, '""')}"`,
      r.city ?? "",
      r.fiscal_year ?? "",
      r.revenue ?? "",
      r.ebit ?? "",
      r.ebitda ?? "",
      r.margin_pct ?? "",
      r.net_profit ?? "",
      r.fte ?? "",
    ].join(",")
  );
  const blob = new Blob([headers.join(",") + "\n" + csvRows.join("\n")], {
    type: "text/csv",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "screener_export.csv";
  a.click();
  URL.revokeObjectURL(url);
}

function marginColor(v: number | null | undefined): string {
  if (v == null) return "text-slate-400";
  if (v >= 15) return "text-emerald-600";
  if (v >= 5) return "text-slate-700";
  if (v >= 0) return "text-amber-600";
  return "text-red-600";
}

/* ------------------------------------------------------------------ */
/*  Compact skeleton                                                   */
/* ------------------------------------------------------------------ */

function SkeletonRows({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <tr key={i} className="border-b border-slate-100">
          <td className="py-2 px-3" colSpan={7}>
            <div className="h-3 w-3/4 animate-pulse rounded bg-slate-200 mb-1" />
            <div className="h-2.5 w-1/2 animate-pulse rounded bg-slate-100" />
          </td>
        </tr>
      ))}
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Sortable column header                                             */
/* ------------------------------------------------------------------ */

function SortHeader({
  label,
  sortKey,
  currentSort,
  onSort,
  align = "right",
}: {
  label: string;
  sortKey: SortKey;
  currentSort: string;
  onSort: (k: SortKey) => void;
  align?: "left" | "right";
}) {
  const isActive = currentSort === sortKey;
  return (
    <th
      className={`py-1.5 px-2 text-[11px] font-semibold uppercase tracking-wider cursor-pointer select-none whitespace-nowrap transition-colors hover:text-indigo-600 ${
        align === "right" ? "text-right" : "text-left"
      } ${isActive ? "text-indigo-700" : "text-slate-500"}`}
      onClick={() => onSort(sortKey)}
    >
      <span className="inline-flex items-center gap-0.5">
        {label}
        {isActive ? (
          <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronUp className="w-3 h-3 opacity-0 group-hover:opacity-30" />
        )}
      </span>
    </th>
  );
}

/* ------------------------------------------------------------------ */
/*  Hover card                                                         */
/* ------------------------------------------------------------------ */

function HoverCard({ row, t }: { row: ScreenerRow; t: (key: string) => string }) {
  return (
    <div className="absolute z-50 left-0 top-full mt-1 w-72 rounded-lg border border-slate-200 bg-white p-3 shadow-lg pointer-events-none">
      <div className="text-xs font-semibold text-slate-800 mb-2 truncate">
        {row.name}
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
        <span className="text-slate-400">{t("screener.hoverCbe")}</span>
        <span className="font-mono text-slate-600">{fmtCbe(row.cbe)}</span>
        <span className="text-slate-400">{t("screener.hoverLegalForm")}</span>
        <span className="text-slate-600">{row.jf_label ?? "\u2014"}</span>
        <span className="text-slate-400">{t("screener.hoverFounded")}</span>
        <span className="text-slate-600">
          {row.start_date ? row.start_date.slice(0, 4) : "\u2014"}
        </span>
        <span className="text-slate-400">{t("screener.hoverNace")}</span>
        <span className="text-slate-600 truncate">{row.nace || "\u2014"}</span>
        <span className="text-slate-400">{t("screener.hoverRevenue")}</span>
        <span className="font-mono text-slate-700">{fmtEur(row.revenue)}</span>
        <span className="text-slate-400">{t("screener.hoverEbit")}</span>
        <span className="font-mono text-slate-700">{fmtEur(row.ebit)}</span>
        <span className="text-slate-400">{t("screener.hoverEbitda")}</span>
        <span className="font-mono text-slate-700">{fmtEur(row.ebitda)}</span>
        <span className="text-slate-400">{t("screener.hoverMargin")}</span>
        <span className={`font-mono ${marginColor(row.margin_pct)}`}>
          {fmtPct(row.margin_pct)}
        </span>
        <span className="text-slate-400">{t("screener.hoverNetProfit")}</span>
        <span className="font-mono text-slate-700">
          {fmtEur(row.net_profit)}
        </span>
        <span className="text-slate-400">{t("screener.hoverFte")}</span>
        <span className="font-mono text-slate-700">{fmtNumber(row.fte)}</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

interface FilterPreset {
  name: string;
  filters: Filters;
  unit: string;
}

const PRESETS_KEY = "datasnoop_screener_presets";

function loadPresets(): FilterPreset[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(PRESETS_KEY) || "[]"); } catch { return []; }
}

function savePresets(presets: FilterPreset[]) {
  localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
}

export default function ScreenerPage() {
  const { t } = useTranslation();
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [results, setResults] = useState<ScreenerRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [fetchMs, setFetchMs] = useState<number | null>(null);
  const [unit, setUnit] = useState<FinancialUnit>("M");
  const [hoveredCbe, setHoveredCbe] = useState<string | null>(null);
  const [nameSearch, setNameSearch] = useState("");
  const [presets, setPresets] = useState<FilterPreset[]>([]);
  const [showSaveInput, setShowSaveInput] = useState(false);
  const [presetName, setPresetName] = useState("");
  const [showPresetMenu, setShowPresetMenu] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => { setPresets(loadPresets()); }, []);

  /* NACE autocomplete */
  const [naceSuggestions, setNaceSuggestions] = useState<NaceSuggestion[]>([]);
  const [naceOpen, setNaceOpen] = useState(false);
  const naceDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const naceContainerRef = useRef<HTMLDivElement>(null);
  const naceInputRef = useRef<HTMLInputElement>(null);
  const [naceDropdownStyle, setNaceDropdownStyle] = useState<React.CSSProperties>({});

  /* Debounced fetch ref */
  const fetchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountFetchedRef = useRef(false);

  const fetchNaceSuggestions = useCallback((q: string) => {
    if (naceDebounceRef.current) clearTimeout(naceDebounceRef.current);
    if (!q || q.length < 1) {
      setNaceSuggestions([]);
      return;
    }
    naceDebounceRef.current = setTimeout(async () => {
      try {
        const data = await getNaceSuggestions(q);
        setNaceSuggestions(data);
      } catch {
        setNaceSuggestions([]);
      }
    }, 200);
  }, []);

  /* Position the NACE dropdown relative to the input */
  const updateNaceDropdownPosition = useCallback(() => {
    const el = naceInputRef.current ?? naceContainerRef.current?.querySelector("input");
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setNaceDropdownStyle({
      position: "fixed" as const,
      top: rect.bottom + 4,
      left: rect.left,
      width: Math.max(rect.width, 400),
      maxWidth: "min(500px, calc(100vw - 32px))",
    });
  }, []);

  /* Close NACE dropdown on outside click */
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        naceContainerRef.current &&
        !naceContainerRef.current.contains(e.target as Node)
      ) {
        setNaceOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  /* ---- Core fetch ---- */
  const doFetch = useCallback(
    async (f: Filters) => {
      setLoading(true);
      const t0 = performance.now();
      try {
        const multiplier = unit === "M" ? 1_000_000 : unit === "K" ? 1_000 : 1;
        const params: Record<string, string> = {};
        if (f.nace) params.nace = f.nace;
        if (f.zipcode) params.zipcode = f.zipcode;
        if (f.rev_min)
          params.rev_min = String(Number(f.rev_min) * multiplier);
        if (f.rev_max)
          params.rev_max = String(Number(f.rev_max) * multiplier);
        if (f.ebit_min)
          params.ebit_min = String(
            Number(f.ebit_min) * (f.ebit_min === "0" ? 1 : multiplier)
          );
        if (f.ebit_max)
          params.ebit_max = String(Number(f.ebit_max) * multiplier);
        if (f.fte_min) params.fte_min = f.fte_min;
        if (f.fte_max) params.fte_max = f.fte_max;
        if (f.margin_min) params.margin_min = f.margin_min;
        if (f.nd_ebitda_max) params.nd_ebitda_max = f.nd_ebitda_max;
        if (f.rev_growth_min) params.rev_growth_min = f.rev_growth_min;
        if (f.rev_growth_max) params.rev_growth_max = f.rev_growth_max;
        if (f.ebitda_growth_min) params.ebitda_growth_min = f.ebitda_growth_min;
        if (f.ebitda_growth_max) params.ebitda_growth_max = f.ebitda_growth_max;
        if (f.assets_growth_min) params.assets_growth_min = f.assets_growth_min;
        if (f.assets_growth_max) params.assets_growth_max = f.assets_growth_max;
        params.sort = f.sort;
        params.limit = f.limit;

        const data = await getScreener(params);
        setResults(data);
        setFetchMs(Math.round(performance.now() - t0));
      } catch (err) {
        console.error("Screener fetch failed:", err);
        setResults([]);
        setFetchMs(null);
      } finally {
        setLoading(false);
      }
    },
    [unit]
  );

  /* Debounced auto-fetch on filter changes */
  const scheduleFetch = useCallback(
    (f: Filters) => {
      if (fetchDebounceRef.current) clearTimeout(fetchDebounceRef.current);
      fetchDebounceRef.current = setTimeout(() => doFetch(f), 400);
    },
    [doFetch]
  );

  const updateFilter = useCallback(
    (key: keyof Filters, value: string) => {
      setFilters((prev) => {
        const next = { ...prev, [key]: value };
        scheduleFetch(next);
        return next;
      });
    },
    [scheduleFetch]
  );

  const resetFilters = useCallback(() => {
    setFilters(DEFAULT_FILTERS);
    setUnit("M");
    setNameSearch("");
    setNaceSuggestions([]);
    setNaceOpen(false);
    doFetch(DEFAULT_FILTERS);
  }, [doFetch]);

  const toggleQuickFilter = useCallback(
    (qf: QuickFilter) => {
      setFilters((prev) => {
        const patch = qf.apply(prev);
        const next = { ...prev, ...patch };
        scheduleFetch(next);
        return next;
      });
    },
    [scheduleFetch]
  );

  const handleSort = useCallback(
    (key: SortKey) => {
      setFilters((prev) => {
        const next = { ...prev, sort: key };
        scheduleFetch(next);
        return next;
      });
    },
    [scheduleFetch]
  );

  /* Re-fetch when unit changes (doFetch captures latest unit) */
  const unitPrevRef = useRef(unit);
  useEffect(() => {
    if (!mountFetchedRef.current) {
      mountFetchedRef.current = true;
      doFetch(DEFAULT_FILTERS);
    } else if (unitPrevRef.current !== unit) {
      doFetch(filters);
    }
    unitPrevRef.current = unit;
  }, [doFetch, unit, filters]);

  /* Client-side name filter (instant, no API call) */
  const filteredResults = useMemo(() => {
    if (!nameSearch.trim()) return results;
    const q = nameSearch.toLowerCase();
    return results.filter(
      (r) =>
        (r.name && r.name.toLowerCase().includes(q)) ||
        r.cbe.includes(q.replace(/\./g, ""))
    );
  }, [results, nameSearch]);

  /* Active filter count for badge */
  const activeFilterCount = useMemo(() => {
    let c = 0;
    if (filters.nace) c++;
    if (filters.zipcode || filters.province) c++;
    if (filters.rev_min || filters.rev_max) c++;
    if (filters.ebit_min || filters.ebit_max) c++;
    if (filters.fte_min || filters.fte_max) c++;
    if (filters.margin_min) c++;
    if (filters.nd_ebitda_max) c++;
    if (filters.rev_growth_min || filters.rev_growth_max) c++;
    if (filters.ebitda_growth_min || filters.ebitda_growth_max) c++;
    if (filters.assets_growth_min || filters.assets_growth_max) c++;
    return c;
  }, [filters]);

  return (
    <div className="flex h-[calc(100vh-64px)] overflow-hidden relative">
      {/* Mobile filter toggle */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="md:hidden fixed bottom-4 right-4 z-40 bg-indigo-600 text-white rounded-full p-3 shadow-lg hover:bg-indigo-700 transition-colors"
      >
        {sidebarOpen ? <X className="w-5 h-5" /> : <SlidersHorizontal className="w-5 h-5" />}
        {!sidebarOpen && activeFilterCount > 0 && (
          <span className="absolute -top-1 -right-1 bg-rose-500 text-white text-[9px] font-bold rounded-full w-4 h-4 flex items-center justify-center">
            {activeFilterCount}
          </span>
        )}
      </button>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="md:hidden fixed inset-0 bg-black/20 z-30" onClick={() => setSidebarOpen(false)} />
      )}

      {/* ================= LEFT SIDEBAR ================= */}
      <aside className={`w-60 shrink-0 border-r border-slate-200 bg-slate-50/70 overflow-y-auto
        fixed md:static inset-y-0 left-0 z-30 transition-transform md:translate-x-0
        ${sidebarOpen ? "translate-x-0" : "-translate-x-full"}
        md:block
      `}>
        <div className="p-3 space-y-3">
          {/* Sidebar header */}
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
              {t("screener.filters")}
            </span>
            {activeFilterCount > 0 && (
              <Badge
                variant="secondary"
                className="text-[10px] bg-indigo-100 text-indigo-700 px-1.5 py-0"
              >
                {activeFilterCount}
              </Badge>
            )}
          </div>

          {/* Reset + Save/Load */}
          <div className="flex items-center gap-3">
            <button
              onClick={resetFilters}
              className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-600 transition-colors"
            >
              <RotateCcw className="w-3 h-3" />
              {t("screener.reset")}
            </button>
            <button
              onClick={() => setShowSaveInput(!showSaveInput)}
              className="flex items-center gap-1 text-[11px] text-indigo-500 hover:text-indigo-700 transition-colors"
            >
              <Save className="w-3 h-3" />
              {t("screener.save")}
            </button>
            {presets.length > 0 && (
              <div className="relative">
                <button
                  onClick={() => setShowPresetMenu(!showPresetMenu)}
                  className="flex items-center gap-1 text-[11px] text-indigo-500 hover:text-indigo-700 transition-colors"
                >
                  <FolderOpen className="w-3 h-3" />
                  {t("screener.load")}
                </button>
                {showPresetMenu && (
                  <div className="absolute top-full left-0 mt-1 w-48 bg-white rounded-lg border shadow-lg z-50 py-1">
                    {presets.map((p, i) => (
                      <div key={i} className="flex items-center justify-between px-2 py-1 hover:bg-slate-50 group">
                        <button
                          className="text-[11px] text-slate-700 truncate flex-1 text-left"
                          onClick={() => {
                            setFilters(p.filters);
                            setUnit(p.unit as FinancialUnit);
                            doFetch(p.filters);
                            setShowPresetMenu(false);
                          }}
                        >
                          {p.name}
                        </button>
                        <button
                          className="text-slate-300 hover:text-rose-500 opacity-0 group-hover:opacity-100 transition-opacity ml-1"
                          onClick={(e) => {
                            e.stopPropagation();
                            const next = presets.filter((_, j) => j !== i);
                            setPresets(next);
                            savePresets(next);
                            if (next.length === 0) setShowPresetMenu(false);
                          }}
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Save preset input */}
          {showSaveInput && (
            <div className="flex gap-1">
              <Input
                className="h-6 text-[11px] flex-1"
                placeholder={t("screener.presetPlaceholder")}
                value={presetName}
                onChange={(e) => setPresetName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && presetName.trim()) {
                    const next = [...presets, { name: presetName.trim(), filters, unit }];
                    setPresets(next);
                    savePresets(next);
                    setPresetName("");
                    setShowSaveInput(false);
                  }
                }}
                autoFocus
              />
              <button
                onClick={() => {
                  if (presetName.trim()) {
                    const next = [...presets, { name: presetName.trim(), filters, unit }];
                    setPresets(next);
                    savePresets(next);
                    setPresetName("");
                    setShowSaveInput(false);
                  }
                }}
                className="text-[10px] text-indigo-600 font-medium px-2 hover:bg-indigo-50 rounded"
              >
                OK
              </button>
            </div>
          )}

          {/* NACE */}
          <div className="space-y-1" ref={naceContainerRef}>
            <Label className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              <Tag className="w-3 h-3 inline mr-1" />
              {t("screener.naceSector")}
            </Label>
            <div className="relative">
              <Input
                ref={naceInputRef}
                className="h-7 text-xs"
                placeholder={t("screener.naceCodeOrName")}
                value={filters.nace}
                onChange={(e) => {
                  updateFilter("nace", e.target.value);
                  fetchNaceSuggestions(e.target.value);
                  updateNaceDropdownPosition();
                }}
                onFocus={() => {
                  setNaceOpen(true);
                  updateNaceDropdownPosition();
                }}
              />
              {naceOpen && naceSuggestions.length > 0 && typeof document !== "undefined" && createPortal(
                <div className="z-[100] bg-white border border-slate-200 rounded-lg shadow-2xl max-h-[60vh] overflow-y-auto" style={naceDropdownStyle}>
                  {naceSuggestions.map((s) => (
                    <button
                      key={s.nace_code}
                      className="w-full text-left px-2 py-1.5 text-[11px] hover:bg-indigo-50 border-b border-slate-50 last:border-0"
                      onClick={() => {
                        updateFilter("nace", s.nace_code);
                        setNaceOpen(false);
                      }}
                    >
                      <span className="font-mono text-indigo-600">
                        {s.nace_code}
                      </span>
                      <span className="text-slate-500 ml-1.5 truncate">
                        {s.description}
                      </span>
                      {s.company_count != null && (
                        <span className="text-slate-300 ml-1">
                          ({s.company_count})
                        </span>
                      )}
                    </button>
                  ))}
                </div>,
                document.body,
              )}
            </div>
          </div>

          {/* Province */}
          <div className="space-y-1">
            <Label className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              <MapPin className="w-3 h-3 inline mr-1" />
              {t("screener.province")}
            </Label>
            <Select
              value={filters.province || "all"}
              onValueChange={(v) => {
                if (v === "all") {
                  setFilters((prev) => {
                    const next = { ...prev, province: "", zipcode: "" };
                    scheduleFetch(next);
                    return next;
                  });
                  return;
                }
                const prov = PROVINCES.find((p) => p.label === v);
                setFilters((prev) => {
                  const next = {
                    ...prev,
                    province: v ?? "",
                    zipcode: prov ? prov.prefix : prev.zipcode,
                  };
                  scheduleFetch(next);
                  return next;
                });
              }}
            >
              <SelectTrigger className="h-7 text-xs w-full">
                <SelectValue placeholder="All" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("screener.allProvinces")}</SelectItem>
                {PROVINCES.map((p) => (
                  <SelectItem key={p.label} value={p.label}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Unit toggle */}
          <div className="pt-1">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
                {t("screener.unit")}
              </span>
              <div className="flex rounded border border-slate-200 overflow-hidden">
                {(["raw", "K", "M"] as FinancialUnit[]).map((u) => (
                  <button
                    key={u}
                    onClick={() => setUnit(u)}
                    className={`px-2 py-0.5 text-[10px] font-semibold transition-colors ${
                      unit === u
                        ? "bg-indigo-600 text-white"
                        : "bg-white text-slate-400 hover:bg-slate-50"
                    }`}
                  >
                    {u === "raw" ? "\u20ac" : u}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Revenue */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              {t("screener.revenue")}{unit !== "raw" ? ` (${unit})` : ""}
            </Label>
            <div className="grid grid-cols-2 gap-1.5">
              <Input
                className="h-7 text-xs font-mono"
                type="number"
                placeholder="Min"
                value={filters.rev_min}
                onChange={(e) => updateFilter("rev_min", e.target.value)}
              />
              <Input
                className="h-7 text-xs font-mono"
                type="number"
                placeholder="Max"
                value={filters.rev_max}
                onChange={(e) => updateFilter("rev_max", e.target.value)}
              />
            </div>
          </div>

          {/* EBIT */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              {t("screener.ebit")}{unit !== "raw" ? ` (${unit})` : ""}
            </Label>
            <div className="grid grid-cols-2 gap-1.5">
              <Input
                className="h-7 text-xs font-mono"
                type="number"
                placeholder="Min"
                value={filters.ebit_min}
                onChange={(e) => updateFilter("ebit_min", e.target.value)}
              />
              <Input
                className="h-7 text-xs font-mono"
                type="number"
                placeholder="Max"
                value={filters.ebit_max}
                onChange={(e) => updateFilter("ebit_max", e.target.value)}
              />
            </div>
          </div>

          {/* FTE */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              {t("screener.fte")}
            </Label>
            <div className="grid grid-cols-2 gap-1.5">
              <Input
                className="h-7 text-xs font-mono"
                type="number"
                placeholder="Min"
                value={filters.fte_min}
                onChange={(e) => updateFilter("fte_min", e.target.value)}
              />
              <Input
                className="h-7 text-xs font-mono"
                type="number"
                placeholder="Max"
                value={filters.fte_max}
                onChange={(e) => updateFilter("fte_max", e.target.value)}
              />
            </div>
          </div>

          {/* Margin */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              {t("screener.marginMin")}
            </Label>
            <Input
              className="h-7 text-xs font-mono"
              type="number"
              placeholder="0"
              value={filters.margin_min}
              onChange={(e) => updateFilter("margin_min", e.target.value)}
            />
          </div>

          {/* Net Debt / EBITDA */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              <TrendingUp className="w-3 h-3 inline mr-1" />
              {t("screener.maxNetDebtEbitda")}
            </Label>
            <Input
              className="h-7 text-xs font-mono"
              type="number"
              placeholder="e.g. 4"
              value={filters.nd_ebitda_max}
              onChange={(e) => updateFilter("nd_ebitda_max", e.target.value)}
            />
          </div>

          {/* ── Growth Filters ── */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              <TrendingUp className="w-3 h-3 inline mr-1" />
              {t("screener.revenueGrowth")}
            </Label>
            <div className="grid grid-cols-2 gap-1">
              <Input
                className="h-7 text-xs font-mono"
                type="number"
                placeholder="Min"
                value={filters.rev_growth_min}
                onChange={(e) => updateFilter("rev_growth_min", e.target.value)}
              />
              <Input
                className="h-7 text-xs font-mono"
                type="number"
                placeholder="Max"
                value={filters.rev_growth_max}
                onChange={(e) => updateFilter("rev_growth_max", e.target.value)}
              />
            </div>
          </div>

          <div className="space-y-1">
            <Label className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              <TrendingUp className="w-3 h-3 inline mr-1" />
              {t("screener.ebitdaGrowth")}
            </Label>
            <div className="grid grid-cols-2 gap-1">
              <Input
                className="h-7 text-xs font-mono"
                type="number"
                placeholder="Min"
                value={filters.ebitda_growth_min}
                onChange={(e) => updateFilter("ebitda_growth_min", e.target.value)}
              />
              <Input
                className="h-7 text-xs font-mono"
                type="number"
                placeholder="Max"
                value={filters.ebitda_growth_max}
                onChange={(e) => updateFilter("ebitda_growth_max", e.target.value)}
              />
            </div>
          </div>

          <div className="space-y-1">
            <Label className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              <TrendingUp className="w-3 h-3 inline mr-1" />
              {t("screener.totalAssetsGrowth")}
            </Label>
            <div className="grid grid-cols-2 gap-1">
              <Input
                className="h-7 text-xs font-mono"
                type="number"
                placeholder="Min"
                value={filters.assets_growth_min}
                onChange={(e) => updateFilter("assets_growth_min", e.target.value)}
              />
              <Input
                className="h-7 text-xs font-mono"
                type="number"
                placeholder="Max"
                value={filters.assets_growth_max}
                onChange={(e) => updateFilter("assets_growth_max", e.target.value)}
              />
            </div>
          </div>

          {/* Limit */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              {t("screener.limit")}
            </Label>
            <Select
              value={filters.limit}
              onValueChange={(v) => updateFilter("limit", v ?? "100")}
            >
              <SelectTrigger className="h-7 text-xs w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LIMIT_OPTIONS.map((opt) => (
                  <SelectItem key={opt} value={opt}>
                    {opt} rows
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </aside>

      {/* ================= MAIN CONTENT ================= */}
      <main className="flex-1 min-w-0 flex flex-col overflow-hidden">
        {/* Top bar: search + quick filters + export */}
        <div className="border-b border-slate-200 bg-white px-4 py-2 space-y-2">
          {/* Row 1: Search + Export */}
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
              <input
                type="text"
                className="w-full h-8 pl-8 pr-3 text-sm border border-slate-200 rounded-md bg-slate-50 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-400 placeholder:text-slate-400"
                placeholder={t("screener.searchResultsPlaceholder")}
                value={nameSearch}
                onChange={(e) => setNameSearch(e.target.value)}
              />
            </div>

            {/* Result count + timing */}
            <div className="flex items-center gap-2 text-[11px] text-slate-400 whitespace-nowrap">
              {loading && (
                <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-500" />
              )}
              {!loading && (
                <span>
                  <span className="font-semibold text-slate-600">
                    {filteredResults.length.toLocaleString()}
                  </span>{" "}
                  {t("screener.companies")}
                  {fetchMs != null && (
                    <span className="text-slate-300 ml-1">in {fetchMs}ms</span>
                  )}
                </span>
              )}
            </div>

            <div className="flex-1" />

            <button
              onClick={() => exportCsv(filteredResults)}
              disabled={filteredResults.length === 0}
              className="flex items-center gap-1.5 h-7 px-3 text-[11px] font-medium text-slate-600 border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Download className="w-3 h-3" />
              {t("screener.export")}
            </button>
          </div>

          {/* Row 2: Quick filters */}
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] text-slate-400 mr-1">{t("screener.quick")}</span>
            {QUICK_FILTERS.map((qf) => {
              const active = qf.isActive(filters);
              return (
                <button
                  key={qf.label}
                  onClick={() => toggleQuickFilter(qf)}
                  className={`h-5 px-2 text-[10px] font-medium rounded-full border transition-all ${
                    active
                      ? "bg-indigo-600 text-white border-indigo-600"
                      : "bg-white text-slate-500 border-slate-200 hover:border-indigo-300 hover:text-indigo-600"
                  }`}
                >
                  {qf.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Results table */}
        <div className="flex-1 overflow-y-auto">
          <table className="w-full border-collapse">
            {/* Sticky header */}
            <thead className="sticky top-0 z-10 bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="py-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500 text-left w-[280px]">
                  {t("screener.company")}
                </th>
                <SortHeader
                  label="Revenue"
                  sortKey="revenue_desc"
                  currentSort={filters.sort}
                  onSort={handleSort}
                />
                <SortHeader
                  label="EBITDA"
                  sortKey="ebitda_desc"
                  currentSort={filters.sort}
                  onSort={handleSort}
                />
                <SortHeader
                  label="EBIT"
                  sortKey="ebit_desc"
                  currentSort={filters.sort}
                  onSort={handleSort}
                />
                <th className="py-1.5 px-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500 text-right whitespace-nowrap">
                  {t("screener.columns.margin")}
                </th>
                <SortHeader
                  label="FTE"
                  sortKey="fte_desc"
                  currentSort={filters.sort}
                  onSort={handleSort}
                />
                <th className="py-1.5 px-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500 text-right">
                  {t("screener.fy")}
                </th>
              </tr>
            </thead>

            <tbody>
              {loading && results.length === 0 && <SkeletonRows count={15} />}

              {!loading && filteredResults.length === 0 && (
                <tr>
                  <td
                    colSpan={7}
                    className="py-20 text-center text-sm text-slate-400"
                  >
                    {t("screener.noMatchFilters")}
                  </td>
                </tr>
              )}

              {filteredResults.map((row) => (
                <tr
                  key={row.cbe}
                  className="group border-b border-slate-100 hover:bg-indigo-50/30 transition-colors relative"
                  onMouseEnter={() => setHoveredCbe(row.cbe)}
                  onMouseLeave={() => setHoveredCbe(null)}
                >
                  {/* Company: 2-line cell */}
                  <td className="py-1.5 px-3 relative">
                    <div className="leading-tight">
                      <Link
                        href={`/company/${row.cbe}`}
                        className="text-sm font-semibold text-slate-800 hover:text-indigo-600 hover:underline decoration-indigo-200 underline-offset-2 truncate block max-w-[260px]"
                        title={row.name}
                      >
                        {row.name || fmtCbe(row.cbe)}
                      </Link>
                      <div className="text-[10px] text-slate-400 font-mono leading-tight mt-0.5">
                        {fmtCbe(row.cbe)}
                        {row.city && (
                          <span className="text-slate-300">
                            {" "}
                            &middot; {row.city}
                          </span>
                        )}
                        {row.jf_label && (
                          <span className="text-slate-300">
                            {" "}
                            &middot; {row.jf_label}
                          </span>
                        )}
                        {row.nace && (
                          <Link
                            href={`/stats?nace=${row.nace.split(" ")[0]}`}
                            className="text-indigo-400 hover:text-indigo-600 transition-colors"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {" "}
                            &middot; {row.nace.split(" ")[0]}
                          </Link>
                        )}
                      </div>
                    </div>
                    {/* Hover card */}
                    {hoveredCbe === row.cbe && <HoverCard row={row} t={t} />}
                  </td>

                  {/* Revenue */}
                  <td className="py-1.5 px-2 text-right font-mono text-sm text-slate-800 whitespace-nowrap">
                    {fmtEur(row.revenue)}
                  </td>

                  {/* EBITDA */}
                  <td className="py-1.5 px-2 text-right font-mono text-sm text-slate-700 whitespace-nowrap">
                    {fmtEur(row.ebitda)}
                  </td>

                  {/* EBIT */}
                  <td className="py-1.5 px-2 text-right font-mono text-sm text-slate-600 whitespace-nowrap">
                    {fmtEur(row.ebit)}
                  </td>

                  {/* Margin (color-coded) */}
                  <td
                    className={`py-1.5 px-2 text-right font-mono text-sm whitespace-nowrap ${marginColor(
                      row.margin_pct
                    )}`}
                  >
                    {fmtPct(row.margin_pct)}
                  </td>

                  {/* FTE */}
                  <td className="py-1.5 px-2 text-right font-mono text-sm text-slate-600 whitespace-nowrap">
                    {fmtNumber(row.fte)}
                  </td>

                  {/* FY */}
                  <td className="py-1.5 px-2 text-right text-[11px] text-slate-400 whitespace-nowrap">
                    {row.fiscal_year ?? "\u2014"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </div>
  );
}
