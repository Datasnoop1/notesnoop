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
import type { NaceSuggestion, ScreenerRow } from "@/lib/api";
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
import AdUnit from "@/components/ad-unit";

/* ------------------------------------------------------------------ */
/*  Types — ScreenerRow + NaceSuggestion imported from @/lib/api (the   */
/*  canonical definitions shared with the screener fetcher). Keep      */
/*  Filters + SortKey etc. local to this page.                          */
/* ------------------------------------------------------------------ */

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
  fte_growth_3y_min: string;
  fte_growth_3y_max: string;
  fixed_assets_min: string;
  fixed_assets_max: string;
  distress: "" | "bankruptcy" | "wco" | "any" | "healthy";
  no_financials: boolean;
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
  fte_growth_3y_min: "",
  fte_growth_3y_max: "",
  fixed_assets_min: "",
  fixed_assets_max: "",
  distress: "",
  no_financials: false,
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
  | "fixed_assets_desc"
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
    "FTE Growth 3y %",
    "Fixed assets",
    "Juridical situation",
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
      (r as any).fte_growth_3y_pct ?? "",
      r.fixed_assets ?? "",
      r.juridical_situation ?? "",
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
          <td className="py-2 px-3" colSpan={8}>
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
      className={`py-1.5 px-2 text-[11px] font-semibold uppercase tracking-wider cursor-pointer select-none whitespace-nowrap transition-colors hover:text-brand ${
        align === "right" ? "text-right" : "text-left"
      } ${isActive ? "text-[color:var(--brand-ink)]" : "text-slate-500"}`}
      onClick={() => onSort(sortKey)}
    >
      <span className="inline-flex items-center gap-0.5">
        {label}
        {isActive ? (
          <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronUp className="w-3 h-3 opacity-30 md:opacity-0 md:group-hover:opacity-30" />
        )}
      </span>
    </th>
  );
}

/* ------------------------------------------------------------------ */
/*  RankPill — "Top N%" pill rendered next to revenue/EBITDA/margin    */
/* ------------------------------------------------------------------ */

function RankPill({
  rank,
  peers,
  label,
}: {
  rank: number | null | undefined;
  peers: number | null | undefined;
  label: string;
}) {
  if (rank == null || typeof rank !== "number") return null;
  // Backend only emits a rank when peer_count >= 10; be defensive anyway.
  if (!peers || peers < 10) return null;
  // percent_rank is 0..1 (0 worst, 1 best). "Top N%" means
  // the row is in the top N% of the population.
  const topPct = Math.max(1, Math.round((1 - rank) * 100));
  const color =
    topPct <= 10 ? "bg-emerald-100 text-emerald-700 border-emerald-200" :
    topPct <= 25 ? "bg-emerald-50 text-emerald-600 border-emerald-200" :
    topPct <= 50 ? "bg-slate-50 text-slate-600 border-slate-200" :
    "bg-amber-50 text-amber-600 border-amber-200";
  return (
    <span
      className={`inline-block rounded-sm border px-1 text-[9px] font-semibold leading-[14px] ${color}`}
      title={`${label}: top ${topPct}% of ${peers} companies in the same NACE-2 sector`}
    >
      {topPct}%
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Sparkline (inline SVG, revenue trend)                              */
/* ------------------------------------------------------------------ */

function Sparkline({
  values,
  width = 60,
  height = 18,
  color = "#6366f1",
}: {
  values: (number | null | undefined)[] | null | undefined;
  width?: number;
  height?: number;
  color?: string;
}) {
  const clean = (values ?? []).filter((v): v is number => typeof v === "number");
  if (clean.length < 2) return <span className="text-slate-300 text-[10px]">—</span>;
  const min = Math.min(...clean);
  const max = Math.max(...clean);
  const range = max - min || 1;
  const stepX = clean.length > 1 ? width / (clean.length - 1) : width;
  const points = clean.map((v, i) => {
    const x = i * stepX;
    const y = height - ((v - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const last = clean[clean.length - 1];
  const first = clean[0];
  const trendColor = last > first ? "#10b981" : last < first ? "#f43f5e" : color;
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="inline-block align-middle"
      aria-hidden="true"
    >
      <polyline
        fill="none"
        stroke={trendColor}
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points.join(" ")}
      />
      <circle
        cx={(clean.length - 1) * stepX}
        cy={height - ((last - min) / range) * height}
        r="1.75"
        fill={trendColor}
      />
    </svg>
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
  try {
    const raw = JSON.parse(localStorage.getItem(PRESETS_KEY) || "[]") as FilterPreset[];
    // Migrate stale presets that contain the removed `mgmt_change_days`
    // key — drop it and merge with current DEFAULT_FILTERS so newly-added
    // filter slots (fte_growth_3y_min/max etc.) hydrate as controlled
    // empty strings rather than undefined.
    return raw.map((p) => {
      // Cast through unknown so we can pick up legacy keys (e.g. the
      // removed `mgmt_change_days`, the renamed real_estate_*) without
      // TS complaining about a direct Filters → Record conversion.
      const filters = { ...(p.filters as unknown as Record<string, unknown>) };
      delete filters["mgmt_change_days"];
      // Migrate the brief-lived `real_estate_min/max` filter that was
      // renamed to `fixed_assets_*` after the operator asked us to widen
      // the metric from rubric 22 (land+buildings) to rubric 20/28.
      if ("real_estate_min" in filters) {
        if (filters["real_estate_min"]) filters["fixed_assets_min"] = filters["real_estate_min"];
        delete filters["real_estate_min"];
      }
      if ("real_estate_max" in filters) {
        if (filters["real_estate_max"]) filters["fixed_assets_max"] = filters["real_estate_max"];
        delete filters["real_estate_max"];
      }
      // Sort key was renamed too — would otherwise yield a 400 from the
      // backend the next time the preset is loaded.
      if (filters["sort"] === "real_estate_desc") filters["sort"] = "fixed_assets_desc";
      return { ...p, filters: { ...DEFAULT_FILTERS, ...filters } as Filters };
    });
  } catch {
    return [];
  }
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
  const [nlQuery, setNlQuery] = useState("");
  const [nlLoading, setNlLoading] = useState(false);

  useEffect(() => { setPresets(loadPresets()); }, []);

  /* NACE autocomplete */
  const [naceSuggestions, setNaceSuggestions] = useState<NaceSuggestion[]>([]);
  const [naceOpen, setNaceOpen] = useState(false);
  const naceDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const naceContainerRef = useRef<HTMLDivElement>(null);
  const naceInputRef = useRef<HTMLInputElement>(null);
  const naceDropdownRef = useRef<HTMLDivElement>(null);
  const [naceDropdownStyle, setNaceDropdownStyle] = useState<React.CSSProperties>({});
  const [naceInput, setNaceInput] = useState("");

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

  /* Close NACE dropdown on outside click (exclude portal dropdown) */
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node;
      if (
        naceContainerRef.current &&
        !naceContainerRef.current.contains(target) &&
        (!naceDropdownRef.current || !naceDropdownRef.current.contains(target))
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
        if (f.fte_growth_3y_min) params.fte_growth_3y_min = f.fte_growth_3y_min;
        if (f.fte_growth_3y_max) params.fte_growth_3y_max = f.fte_growth_3y_max;
        if (f.fixed_assets_min)
          params.fixed_assets_min = String(Number(f.fixed_assets_min) * multiplier);
        if (f.fixed_assets_max)
          params.fixed_assets_max = String(Number(f.fixed_assets_max) * multiplier);
        if (f.distress) params.distress = f.distress;
        if (f.no_financials) params.no_financials = "true";
        params.include_sparklines = "true";
        params.include_percentiles = "true";
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

  const [naceChips, setNaceChips] = useState<string[]>([]);

  const buildNaceFilter = useCallback((chips: string[], typed: string) => {
    const parts = [...chips];
    if (typed.trim()) parts.push(typed.trim());
    return parts.join(",");
  }, []);

  const addNace = useCallback((code: string) => {
    setNaceChips((prev) => {
      if (prev.includes(code)) return prev;
      const next = [...prev, code];
      const combined = next.join(",");
      setFilters((f) => {
        const nf = { ...f, nace: combined };
        scheduleFetch(nf);
        return nf;
      });
      return next;
    });
    setNaceInput("");
    setNaceSuggestions([]);
  }, [scheduleFetch]);

  const removeNace = useCallback((code: string) => {
    setNaceChips((prev) => {
      const next = prev.filter((c) => c !== code);
      const combined = buildNaceFilter(next, naceInput);
      setFilters((f) => {
        const nf = { ...f, nace: combined };
        scheduleFetch(nf);
        return nf;
      });
      return next;
    });
  }, [scheduleFetch, buildNaceFilter, naceInput]);

  const resetFilters = useCallback(() => {
    setFilters(DEFAULT_FILTERS);
    setUnit("M");
    setNameSearch("");
    setNaceInput("");
    setNaceChips([]);
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
    if (filters.fte_growth_3y_min || filters.fte_growth_3y_max) c++;
    if (filters.fixed_assets_min || filters.fixed_assets_max) c++;
    if (filters.distress) c++;
    return c;
  }, [filters]);

  return (
    <div className="flex h-[calc(100dvh-116px)] md:h-[calc(100vh-64px)] overflow-hidden relative">
      {/* Mobile filter toggle — positioned above the ad banner */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="md:hidden fixed bottom-20 right-4 z-40 bg-brand text-white rounded-full p-3 shadow-lg hover:bg-[color:var(--brand-ink)] transition-colors"
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
      <aside className={`w-[85vw] max-w-xs md:w-60 shrink-0 border-r border-[#E3EAF4] bg-[#F8FAFD] overflow-y-auto
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
                className="text-[10px] bg-brand-soft text-[color:var(--brand-ink)] px-1.5 py-0"
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
              className="flex items-center gap-1 text-[11px] text-brand hover:text-[color:var(--brand-ink)] transition-colors"
            >
              <Save className="w-3 h-3" />
              {t("screener.save")}
            </button>
            {presets.length > 0 && (
              <div className="relative">
                <button
                  onClick={() => setShowPresetMenu(!showPresetMenu)}
                  className="flex items-center gap-1 text-[11px] text-brand hover:text-[color:var(--brand-ink)] transition-colors"
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
                          aria-label={`Remove preset ${p.name}`}
                          title="Remove preset"
                          className="text-slate-300 hover:text-rose-500 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity ml-1"
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
                className="text-[10px] text-brand font-medium px-2 hover:bg-brand-soft/60 rounded"
              >
                OK
              </button>
            </div>
          )}

          {/* NACE (multi-select with chips) */}
          <div className="space-y-1" ref={naceContainerRef}>
            <Label className="text-[11px] md:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              <Tag className="w-3 h-3 inline mr-1" />
              {t("screener.naceSector")}
            </Label>
            {naceChips.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {naceChips.map((code) => (
                  <span key={code} className="inline-flex items-center gap-0.5 bg-brand-soft text-[color:var(--brand-ink)] text-[10px] font-mono px-1.5 py-0.5 rounded-md border border-brand/20">
                    {code}
                    <button type="button" onClick={() => removeNace(code)} className="hover:text-[color:var(--brand-ink)] ml-0.5">
                      <X className="w-2.5 h-2.5" />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="relative">
              <Input
                ref={naceInputRef}
                className="h-10 md:h-7 text-base md:text-xs"
                placeholder={naceChips.length ? "Add another..." : t("screener.naceCodeOrName")}
                value={naceInput}
                onChange={(e) => {
                  const val = e.target.value;
                  setNaceInput(val);
                  fetchNaceSuggestions(val);
                  updateNaceDropdownPosition();
                  const combined = buildNaceFilter(naceChips, val);
                  updateFilter("nace", combined);
                }}
                onFocus={() => {
                  setNaceOpen(true);
                  updateNaceDropdownPosition();
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && naceInput.trim()) {
                    e.preventDefault();
                    addNace(naceInput.trim());
                    setNaceOpen(false);
                  }
                }}
              />
              {naceOpen && naceSuggestions.length > 0 && typeof document !== "undefined" && createPortal(
                <div ref={naceDropdownRef} className="z-[100] bg-white border border-slate-200 rounded-lg shadow-2xl max-h-[60vh] overflow-y-auto" style={naceDropdownStyle}>
                  {naceSuggestions.filter((s) => !naceChips.includes(s.nace_code)).map((s) => (
                    <button
                      key={s.nace_code}
                      className="w-full text-left px-2 py-1.5 text-[11px] hover:bg-brand-soft/60 border-b border-slate-50 last:border-0"
                      onClick={() => {
                        addNace(s.nace_code);
                        setNaceOpen(false);
                      }}
                    >
                      <span className="font-mono text-brand">
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
            <Label className="text-[11px] md:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
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
              <SelectTrigger className="h-10 md:h-7 text-base md:text-xs w-full">
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
                        ? "bg-brand text-white"
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
            <Label className="text-[11px] md:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              {t("screener.revenue")}{unit !== "raw" ? ` (${unit})` : ""}
            </Label>
            <div className="grid grid-cols-2 gap-1.5">
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Min"
                value={filters.rev_min}
                onChange={(e) => updateFilter("rev_min", e.target.value)}
              />
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Max"
                value={filters.rev_max}
                onChange={(e) => updateFilter("rev_max", e.target.value)}
              />
            </div>
          </div>

          {/* EBIT */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[11px] md:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              {t("screener.ebit")}{unit !== "raw" ? ` (${unit})` : ""}
            </Label>
            <div className="grid grid-cols-2 gap-1.5">
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Min"
                value={filters.ebit_min}
                onChange={(e) => updateFilter("ebit_min", e.target.value)}
              />
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Max"
                value={filters.ebit_max}
                onChange={(e) => updateFilter("ebit_max", e.target.value)}
              />
            </div>
          </div>

          {/* FTE */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[11px] md:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              {t("screener.fte")}
            </Label>
            <div className="grid grid-cols-2 gap-1.5">
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Min"
                value={filters.fte_min}
                onChange={(e) => updateFilter("fte_min", e.target.value)}
              />
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Max"
                value={filters.fte_max}
                onChange={(e) => updateFilter("fte_max", e.target.value)}
              />
            </div>
          </div>

          {/* Margin */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[11px] md:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              {t("screener.marginMin")}
            </Label>
            <Input
              className="h-10 md:h-7 text-base md:text-xs font-mono"
              type="number"
              placeholder="0"
              value={filters.margin_min}
              onChange={(e) => updateFilter("margin_min", e.target.value)}
            />
          </div>

          {/* Net Debt / EBITDA */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[11px] md:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              <TrendingUp className="w-3 h-3 inline mr-1" />
              {t("screener.maxNetDebtEbitda")}
            </Label>
            <Input
              className="h-10 md:h-7 text-base md:text-xs font-mono"
              type="number"
              placeholder="e.g. 4"
              value={filters.nd_ebitda_max}
              onChange={(e) => updateFilter("nd_ebitda_max", e.target.value)}
            />
          </div>

          {/* ── Growth Filters ── */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[11px] md:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              <TrendingUp className="w-3 h-3 inline mr-1" />
              {t("screener.revenueGrowth")}
            </Label>
            <div className="grid grid-cols-2 gap-1">
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Min"
                value={filters.rev_growth_min}
                onChange={(e) => updateFilter("rev_growth_min", e.target.value)}
              />
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Max"
                value={filters.rev_growth_max}
                onChange={(e) => updateFilter("rev_growth_max", e.target.value)}
              />
            </div>
          </div>

          <div className="space-y-1">
            <Label className="text-[11px] md:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              <TrendingUp className="w-3 h-3 inline mr-1" />
              {t("screener.ebitdaGrowth")}
            </Label>
            <div className="grid grid-cols-2 gap-1">
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Min"
                value={filters.ebitda_growth_min}
                onChange={(e) => updateFilter("ebitda_growth_min", e.target.value)}
              />
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Max"
                value={filters.ebitda_growth_max}
                onChange={(e) => updateFilter("ebitda_growth_max", e.target.value)}
              />
            </div>
          </div>

          {/* Fixed assets (rubric 20/28 — intangible + tangible + financial) */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[11px] md:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              {t("screener.fixedAssets")}
            </Label>
            <div className="grid grid-cols-2 gap-1">
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Min"
                value={filters.fixed_assets_min}
                onChange={(e) => updateFilter("fixed_assets_min", e.target.value)}
              />
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Max"
                value={filters.fixed_assets_max}
                onChange={(e) => updateFilter("fixed_assets_max", e.target.value)}
              />
            </div>
          </div>

          {/* Distress / juridical situation */}
          <div className="space-y-1">
            <Label className="text-[11px] md:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              {t("screener.distress")}
            </Label>
            <Select
              value={filters.distress || "none"}
              onValueChange={(v) =>
                updateFilter(
                  "distress",
                  v === "none" || !v ? "" : (v as "bankruptcy" | "wco" | "any" | "healthy")
                )
              }
            >
              <SelectTrigger className="h-10 md:h-7 text-base md:text-xs w-full">
                <SelectValue placeholder={t("screener.distressAny")} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("screener.distressAny")}</SelectItem>
                <SelectItem value="healthy">{t("screener.distressHealthy")}</SelectItem>
                <SelectItem value="bankruptcy">{t("screener.distressBankruptcy")}</SelectItem>
                <SelectItem value="wco">{t("screener.distressWco")}</SelectItem>
                <SelectItem value="any">{t("screener.distressAnyDistress")}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Coverage-gap mode: show only enterprises not yet in NBB filings */}
          <div className="flex items-center gap-2 pt-1">
            <input
              type="checkbox"
              id="no-financials-toggle"
              checked={filters.no_financials}
              onChange={(e) => {
                setFilters((prev) => {
                  const next = { ...prev, no_financials: e.target.checked };
                  scheduleFetch(next);
                  return next;
                });
              }}
              className="h-3.5 w-3.5 rounded border-slate-300"
            />
            <label
              htmlFor="no-financials-toggle"
              className="text-[11px] md:text-[10px] text-slate-500 cursor-pointer select-none"
            >
              {t("screener.noFinancialsOnly")}
            </label>
          </div>

          {/* FTE 3-year growth — replaces the old Mgmt Change filter.
              Sustained headcount growth is a stronger signal of scale-up
              than a flag for a single management change in the last X days. */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[11px] md:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              <TrendingUp className="w-3 h-3 inline mr-1" />
              {t("screener.fteGrowth3y")}
            </Label>
            <div className="grid grid-cols-2 gap-1">
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Min"
                value={filters.fte_growth_3y_min}
                onChange={(e) => updateFilter("fte_growth_3y_min", e.target.value)}
              />
              <Input
                className="h-10 md:h-7 text-base md:text-xs font-mono"
                type="number"
                placeholder="Max"
                value={filters.fte_growth_3y_max}
                onChange={(e) => updateFilter("fte_growth_3y_max", e.target.value)}
              />
            </div>
          </div>

          {/* Limit */}
          <div className="space-y-1 border-t border-slate-200 pt-2">
            <Label className="text-[11px] md:text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
              {t("screener.limit")}
            </Label>
            <Select
              value={filters.limit}
              onValueChange={(v) => updateFilter("limit", v ?? "100")}
            >
              <SelectTrigger className="h-10 md:h-7 text-base md:text-xs w-full">
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
        <div className="border-b border-[#E3EAF4] bg-white px-4 py-2 space-y-2">
          {/* Row 1: Search + Export */}
          <div className="flex items-center gap-3">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
              <input
                type="text"
                className="w-full h-10 md:h-8 pl-8 pr-3 text-base md:text-sm border border-slate-200 rounded-md bg-slate-50 focus:outline-none focus:ring-2 focus:ring-brand/20 focus:border-brand/60 placeholder:text-slate-400"
                placeholder={t("screener.searchResultsPlaceholder")}
                value={nameSearch}
                onChange={(e) => setNameSearch(e.target.value)}
              />
            </div>

            {/* Result count + timing */}
            <div className="flex items-center gap-2 text-[11px] text-slate-400 whitespace-nowrap">
              {loading && (
                <Loader2 className="w-3.5 h-3.5 animate-spin text-brand" />
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
              className="flex items-center gap-1.5 h-10 md:h-7 px-3 text-xs md:text-[11px] font-medium text-slate-600 border border-slate-200 rounded-md hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
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
                  className={`h-8 md:h-5 px-3 md:px-2 text-[11px] md:text-[10px] font-medium rounded-full border transition-all ${
                    active
                      ? "bg-brand text-white border-brand"
                      : "bg-white text-slate-500 border-slate-200 hover:border-brand/40 hover:text-brand"
                  }`}
                >
                  {qf.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Ad placement: above results */}
        <div className="border-b border-slate-100 no-print">
          <AdUnit slot="3722838377" format="horizontal" className="max-h-[90px] overflow-hidden" />
        </div>

        {/* Results table. Scrollbar hidden from md+ only; mobile keeps the
            native scrollbar so users know the columns scroll (architecture
            gotcha #8). */}
        <div className="flex-1 overflow-y-auto overflow-x-auto md:scrollbar-none relative">
          {/* Loading overlay — sticky so it stays visible at the top-right
              of the visible viewport even when the user has scrolled the
              table down. The previous `absolute top-2` scrolled away with
              the content, defeating the purpose. */}
          {loading && (
            <div className="pointer-events-none sticky top-0 z-20 h-0">
              <div className="absolute right-3 top-2 inline-flex items-center gap-1.5 rounded-full bg-brand text-white px-3 py-1 text-[11px] font-medium shadow-lg">
                <Loader2 className="h-3 w-3 animate-spin" />
                {t("screener.loading")}
              </div>
            </div>
          )}
          <table className="w-full border-collapse min-w-[700px]">
            {/* Sticky header */}
            <thead className="sticky top-0 z-10 bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="py-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-500 text-left w-[140px] md:w-[280px] sticky left-0 z-[11] bg-slate-50 shadow-[1px_0_0_rgba(226,232,240,1)]">
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
                <SortHeader
                  label={t("screener.fixedAssetsShort")}
                  sortKey="fixed_assets_desc"
                  currentSort={filters.sort}
                  onSort={handleSort}
                />
                <th
                  className="py-1.5 px-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500 text-right whitespace-nowrap"
                  title={t("screener.trendHelp")}
                >
                  {t("screener.ebitdaTrend")}
                </th>
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
                    colSpan={8}
                    className="py-20 text-center text-sm text-slate-400"
                  >
                    {t("screener.noMatchFilters")}
                  </td>
                </tr>
              )}

              {filteredResults.map((row) => (
                <tr
                  key={row.cbe}
                  className="group border-b border-slate-100 hover:bg-brand-soft/30 transition-colors relative"
                  onMouseEnter={() => setHoveredCbe(row.cbe)}
                  onMouseLeave={() => setHoveredCbe(null)}
                >
                  {/* Company: 2-line cell — sticky on mobile so the name
                      stays visible when horizontally scrolling the financial
                      columns. */}
                  <td className="py-1.5 px-3 relative sticky left-0 z-[5] bg-white group-hover:bg-brand-soft/30 shadow-[1px_0_0_rgba(226,232,240,1)] w-[140px] md:w-auto">
                    <div className="leading-tight">
                      <Link
                        href={`/company/${row.cbe}`}
                        className="text-sm font-semibold text-slate-800 hover:text-brand hover:underline decoration-brand/30 underline-offset-2 truncate block max-w-[160px] md:max-w-[260px]"
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
                            className="text-brand/60 hover:text-brand transition-colors"
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
                    <span className="inline-flex items-center gap-1 justify-end">
                      {fmtEur(row.revenue)}
                      <RankPill rank={row.rev_rank_pct} peers={row.peer_count} label="Revenue" />
                    </span>
                  </td>

                  {/* EBITDA */}
                  <td className="py-1.5 px-2 text-right font-mono text-sm text-slate-700 whitespace-nowrap">
                    <span className="inline-flex items-center gap-1 justify-end">
                      {fmtEur(row.ebitda)}
                      <RankPill rank={row.ebitda_rank_pct} peers={row.peer_count} label="EBITDA" />
                    </span>
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
                    <span className="inline-flex items-center gap-1 justify-end">
                      {fmtPct(row.margin_pct)}
                      <RankPill rank={row.margin_rank_pct} peers={row.peer_count} label="Margin" />
                    </span>
                  </td>

                  {/* FTE */}
                  <td className="py-1.5 px-2 text-right font-mono text-sm text-slate-600 whitespace-nowrap">
                    {fmtNumber(row.fte)}
                  </td>

                  {/* Vaste activa (fixed assets, rubric 20/28) */}
                  <td className="py-1.5 px-2 text-right font-mono text-sm text-slate-600 whitespace-nowrap">
                    {fmtEur(row.fixed_assets)}
                  </td>

                  {/* EBITDA trend sparkline — EBITDA is what matters for PE
                      screening + it's disclosed by every filer (revenue is
                      optional for micros). Fallback to revenue only if
                      EBITDA is missing (very rare). */}
                  {(() => {
                    const ebitdaClean = (row.ebitda_history ?? []).filter(
                      (v): v is number => typeof v === "number",
                    );
                    const useRevenue = ebitdaClean.length < 2;
                    const series = useRevenue ? row.rev_history : row.ebitda_history;
                    const label = useRevenue ? t("screener.revenue") : "EBITDA";
                    const title = series && series.some((v) => v != null)
                      ? `${label}\n` +
                        (series as (number | null)[])
                          .map((v, i) => {
                            const yr = row.year_history?.[i] ?? "";
                            return `FY${yr}: ${v != null ? fmtEur(v) : "—"}`;
                          })
                          .join("\n")
                      : "";
                    return (
                      <td
                        className="py-1.5 px-2 text-right whitespace-nowrap"
                        title={title}
                      >
                        <Sparkline values={series} />
                        {useRevenue && series && series.some((v) => v != null) && (
                          <span className="ml-1 text-[9px] uppercase text-slate-400 align-middle" title="Revenue fallback">
                            R
                          </span>
                        )}
                      </td>
                    );
                  })()}

                  {/* FY */}
                  <td className="py-1.5 px-2 text-right text-[11px] text-slate-400 whitespace-nowrap">
                    {row.fiscal_year ?? "\u2014"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {/* Recently viewed companies — frontend-only via localStorage */}
        <RecentlyViewedPanel />
      </main>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Recently-viewed panel (collapsible)                                */
/* ------------------------------------------------------------------ */

import { getRecentlyViewed, removeRecentlyViewed, clearRecentlyViewed, type RecentlyViewedEntry } from "@/lib/recently-viewed";

function RecentlyViewedPanel() {
  const { t } = useTranslation();
  const [items, setItems] = useState<RecentlyViewedEntry[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const refresh = () => setItems(getRecentlyViewed());
    refresh();
    const storageHandler = (e: StorageEvent) => {
      if (e.key && !e.key.startsWith("datasnoop_recently_viewed")) return;
      refresh();
    };
    window.addEventListener("storage", storageHandler);
    window.addEventListener("datasnoop:recently-viewed-changed", refresh);
    return () => {
      window.removeEventListener("storage", storageHandler);
      window.removeEventListener("datasnoop:recently-viewed-changed", refresh);
    };
  }, []);

  if (items.length === 0) return null;

  return (
    <div className="border-t border-slate-100 px-3 md:px-4 py-2 bg-slate-50/40">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500 hover:text-slate-700"
      >
        <span>{t("screener.recentlyViewed")}</span>
        <span className="text-slate-300">·</span>
        <span className="text-slate-400 normal-case tracking-normal font-medium">
          {items.length}
        </span>
        <span className="text-slate-400 ml-1">{open ? "\u25BE" : "\u25B8"}</span>
      </button>
      {open && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {items.map((it) => (
            <div
              key={it.cbe}
              className="group inline-flex items-center gap-1 rounded-full bg-white border border-slate-200 px-2 py-0.5 text-[11px] hover:border-brand/40"
            >
              <Link
                href={`/company/${it.cbe}`}
                className="text-slate-700 hover:text-brand max-w-[180px] truncate"
                title={`${it.name}${it.city ? ` · ${it.city}` : ""}`}
              >
                {it.name}
              </Link>
              <button
                onClick={() => {
                  removeRecentlyViewed(it.cbe);
                }}
                className="text-slate-300 opacity-100 md:opacity-0 md:group-hover:opacity-100 hover:text-slate-600 p-1 -m-1"
                title={t("screener.recentlyViewedRemove")}
              >
                ×
              </button>
            </div>
          ))}
          {items.length > 0 && (
            <button
              onClick={clearRecentlyViewed}
              className="text-[10px] text-slate-400 hover:text-slate-600 ml-1"
            >
              {t("screener.recentlyViewedClear")}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
