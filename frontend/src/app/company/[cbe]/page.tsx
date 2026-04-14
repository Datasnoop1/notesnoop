"use client";

import { useState, useEffect, useCallback, use } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import {
  getCompanyDetail,
  getCompanyFinancials,
  getCompanyStructure,
  addFavourite,
  removeFavourite,
} from "@/lib/api";
import { fmtEur, fmtCbe, fmtPct, fmtNumber } from "@/lib/format";
import { useRouter } from "next/navigation";
import {
  Star,
  ArrowLeft,
  ExternalLink,
  ChevronDown,
  ChevronRight,
  Users,
  Network,
  GitBranch,
  FileText,
  Download,
  Shield,
  Scale,
  BarChart3,
  DollarSign,
  TrendingUp,
  Percent,
  Activity,
  Calendar,
  UserCheck,
  Newspaper,
  Loader2,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import dynamic from "next/dynamic";

const NetworkGraph = dynamic(() => import("@/components/network-graph"), {
  ssr: false,
  loading: () => <div className="py-8 text-center text-sm text-slate-400">Loading graph...</div>,
});
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

/* ---------- types ---------- */

interface CompanyDetail {
  enterprise_number: string;
  status: string;
  start_date: string | null;
  jf_label: string | null;
  name: string | null;
  zipcode: string | null;
  city: string | null;
  municipality: string | null;
  street: string | null;
  house_number: string | null;
  nace_code: string | null;
  nace_label: string | null;
  website: string | null;
}

interface FinancialRow {
  fiscal_year: number;
  deposit_key: string | null;
  filing_model: string | null;
  revenue: number | null;
  ebit: number | null;
  da: number | null;
  ebitda: number | null;
  net_profit: number | null;
  equity: number | null;
  lt_financial_debt: number | null;
  st_financial_debt: number | null;
  cash: number | null;
  total_assets: number | null;
  fixed_assets: number | null;
  inventories: number | null;
  trade_receivables: number | null;
  trade_payables: number | null;
  financial_charges: number | null;
  current_investments: number | null;
  fte_total: number | null;
  personnel_costs: number | null;
  ebitda_margin_pct: number | null;
}

interface Administrator {
  name: string;
  role: string;
  role_label: string;
  mandate_start: string | null;
  mandate_end: string | null;
  identifier: string | null;
  person_type: string | null;
}

interface Shareholder {
  name: string;
  ownership_pct: number | null;
  shareholder_type: string | null;
  identifier: string | null;
  fiscal_year: string | null;
}

interface ParticipatingInterest {
  name: string;
  ownership_pct: number | null;
  country: string | null;
  identifier: string | null;
  fiscal_year: string | null;
}

interface StaatsbladPub {
  pub_date: string;
  pub_type: string | null;
  reference: string | null;
  pdf_url: string | null;
}

interface StructureData {
  administrators: Administrator[];
  participating_interests: ParticipatingInterest[];
  shareholders: Shareholder[];
  staatsblad_publications: StaatsbladPub[];
}

interface FinancialsData {
  summary: FinancialRow[];
  rubric_data?: Record<string, Record<string, number | null>>;
}

/* ---------- helper to clean CBE from identifier ---------- */

function cleanCbe(id: string | null): string | null {
  if (!id) return null;
  const c = id.replace(/\./g, "").replace(/ /g, "").trim();
  return /^\d{10}$/.test(c) ? c : null;
}

/* ---------- publication type mapping ---------- */

const PUB_TYPE_MAP: Record<string, { label: string; color: string; summary: string }> = {
  "ONTSLAGEN - BENOEMINGEN": {
    label: "Board",
    color: "bg-blue-100 text-blue-700",
    summary: "Board changes: resignations and appointments",
  },
  "OPRICHTING": {
    label: "Formation",
    color: "bg-green-100 text-green-700",
    summary: "Company formation / incorporation",
  },
  "STATUTENWIJZIGING": {
    label: "Statutes",
    color: "bg-purple-100 text-purple-700",
    summary: "Amendment of articles of association",
  },
  "ONTBINDING": {
    label: "Dissolution",
    color: "bg-red-100 text-red-700",
    summary: "Dissolution",
  },
  "VEREFFENING": {
    label: "Liquidation",
    color: "bg-red-100 text-red-700",
    summary: "Liquidation",
  },
  "FUSIE": {
    label: "Merger",
    color: "bg-amber-100 text-amber-700",
    summary: "Merger",
  },
  "SPLITSING": {
    label: "Demerger",
    color: "bg-amber-100 text-amber-700",
    summary: "Demerger / split",
  },
  "ZETELVERPLAATSING": {
    label: "Relocation",
    color: "bg-cyan-100 text-cyan-700",
    summary: "Registered office relocation",
  },
  "KAPITAALVERHOGING": {
    label: "Cap. increase",
    color: "bg-emerald-100 text-emerald-700",
    summary: "Capital increase",
  },
  "KAPITAALVERMINDERING": {
    label: "Cap. decrease",
    color: "bg-orange-100 text-orange-700",
    summary: "Capital decrease",
  },
  "JAARREKENING": {
    label: "Accounts",
    color: "bg-slate-100 text-slate-600",
    summary: "Annual accounts filing",
  },
};

/* ---------- skeleton ---------- */

function HeaderSkeleton() {
  return (
    <div className="space-y-3 py-6">
      <div className="h-7 w-80 animate-pulse rounded bg-slate-200" />
      <div className="h-4 w-48 animate-pulse rounded bg-slate-200" />
      <div className="flex gap-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="h-4 w-32 animate-pulse rounded bg-slate-200"
          />
        ))}
      </div>
    </div>
  );
}

function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, i) => (
        <TableRow key={i}>
          {Array.from({ length: 10 }).map((_, j) => (
            <TableCell key={j}>
              <div className="h-4 w-full animate-pulse rounded bg-slate-200" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

/* ---------- custom tooltip for chart ---------- */

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-white p-3 shadow-md">
      <p className="mb-1 text-xs font-semibold text-slate-700">FY {label}</p>
      {payload.map((entry) => (
        <p key={entry.name} className="text-xs" style={{ color: entry.color }}>
          {entry.name}: {fmtEur(entry.value)}
        </p>
      ))}
    </div>
  );
}

/* ---------- main component ---------- */

export default function CompanyDetailPage(props: {
  params: Promise<{ cbe: string }>;
}) {
  const { cbe } = use(props.params);

  const [detail, setDetail] = useState<CompanyDetail | null>(null);
  const [financials, setFinancials] = useState<FinancialsData | null>(null);
  const [structure, setStructure] = useState<StructureData | null>(null);
  const [loading, setLoading] = useState(true);
  const [isFavourite, setIsFavourite] = useState(false);
  const [activeTab, setActiveTab] = useState("summary");
  const [nbbLoading, setNbbLoading] = useState(false);
  const [nbbResult, setNbbResult] = useState<"success" | "error" | null>(null);
  const router = useRouter();

  useEffect(() => {
    setLoading(true);
    Promise.all([
      getCompanyDetail(cbe),
      getCompanyFinancials(cbe),
      getCompanyStructure(cbe),
    ])
      .then(([d, f, s]) => {
        setDetail(d as unknown as CompanyDetail);
        setFinancials(f as unknown as FinancialsData);
        setStructure(s as unknown as StructureData);
      })
      .catch((err) => {
        console.error("Failed to load company data:", err);
      })
      .finally(() => setLoading(false));
  }, [cbe]);

  const toggleFavourite = useCallback(async () => {
    try {
      if (isFavourite) {
        await removeFavourite(cbe);
        setIsFavourite(false);
      } else {
        await addFavourite(cbe);
        setIsFavourite(true);
      }
    } catch {
      // Requires login — silently fail
    }
  }, [cbe, isFavourite]);

  const handleTabChange = useCallback(
    (value: any) => {
      if (typeof value === "string") {
        setActiveTab(value);
      }
    },
    []
  );

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4">
        <HeaderSkeleton />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 py-16 text-center">
        <p className="text-lg font-medium text-slate-700">Company not found</p>
        <p className="mt-1 text-sm text-slate-500">
          CBE {fmtCbe(cbe)} could not be loaded.
        </p>
        <Link
          href="/company"
          className="mt-4 inline-flex items-center gap-1 text-sm text-indigo-600 hover:underline"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back to search
        </Link>
      </div>
    );
  }

  const addressParts = [
    detail.street,
    detail.house_number,
    [detail.zipcode, detail.city].filter(Boolean).join(" "),
  ].filter(Boolean);
  const address = addressParts.length > 0 ? addressParts.join(", ") : null;

  /* Chart data */
  const chartData = (financials?.summary ?? []).map((r) => ({
    fy: String(r.fiscal_year),
    Revenue: r.revenue,
    EBITDA: r.ebitda,
  }));

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 py-4">
      {/* Back link */}
      <Link
        href="/company"
        className="mb-3 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-indigo-600"
      >
        <ArrowLeft className="h-3 w-3" /> Back to search
      </Link>

      {/* ━━━ Company Header ━━━ */}
      <div className="mb-8">
        {/* Top row: name + actions */}
        <div className="flex items-start justify-between gap-6">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold text-slate-900">
              {detail.name || fmtCbe(cbe)}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-400">
              <span className="font-mono text-xs text-slate-500">{fmtCbe(cbe)}</span>
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${detail.status === "AC" ? "bg-emerald-500" : "bg-red-400"}`} />
              <span className="text-xs">{detail.status === "AC" ? "Active" : "Ceased"}</span>
              {detail.start_date && (
                <span className="text-xs">Est. {detail.start_date.slice(0, 4)}</span>
              )}
            </div>
            {/* Single subtle info line */}
            <div className="mt-2 flex flex-wrap items-center gap-x-4 text-xs text-slate-400">
              {address && (
                <span>{address}</span>
              )}
              {detail.nace_code && (
                <span>
                  NACE {detail.nace_code}{detail.nace_label && detail.nace_label !== detail.nace_code ? ` \u2014 ${detail.nace_label}` : ""}
                </span>
              )}
              {detail.jf_label && (
                <span>{detail.jf_label}</span>
              )}
              {detail.website && (
                <a
                  href={detail.website.startsWith("http") ? detail.website : `https://${detail.website}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-indigo-500 hover:text-indigo-700 transition-colors"
                >
                  {detail.website.replace(/^https?:\/\//, "")}
                </a>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0 pt-1">
            <Button
              variant="outline"
              size="sm"
              onClick={toggleFavourite}
              title={isFavourite ? "Remove from favourites" : "Add to favourites"}
              className="h-8 px-2.5 text-slate-400 hover:text-yellow-500 border-slate-200"
            >
              <Star
                className={`h-3.5 w-3.5 ${
                  isFavourite
                    ? "fill-yellow-400 text-yellow-500"
                    : ""
                }`}
              />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                const existing = JSON.parse(sessionStorage.getItem("compare_companies") || "[]");
                if (!existing.includes(cbe)) {
                  existing.push(cbe);
                  sessionStorage.setItem("compare_companies", JSON.stringify(existing));
                }
                router.push("/compare");
              }}
              className="h-8 text-xs text-slate-500 border-slate-200 hover:border-slate-300"
            >
              <Scale className="w-3 h-3 mr-1.5" />
              Compare
            </Button>
          </div>
        </div>

        {/* KPI cards */}
        {(() => {
          const latest = financials?.summary?.length
            ? [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year)[0]
            : null;
          if (!latest) return null;

          const marginVal = latest.ebitda_margin_pct;
          const marginColor =
            marginVal == null
              ? "text-slate-900"
              : marginVal >= 15
                ? "text-emerald-600"
                : marginVal >= 5
                  ? "text-amber-600"
                  : marginVal < 0
                    ? "text-red-600"
                    : "text-slate-900";

          return (
            <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="rounded-xl border border-slate-100 bg-white px-5 py-4">
                <div className="text-xs text-slate-400 mb-1">Revenue <span className="font-mono text-slate-300">FY{latest.fiscal_year}</span></div>
                <div className="text-lg font-semibold text-slate-900 font-mono tracking-tight">{fmtEur(latest.revenue)}</div>
              </div>
              <div className="rounded-xl border border-slate-100 bg-white px-5 py-4">
                <div className="text-xs text-slate-400 mb-1">EBITDA <span className="font-mono text-slate-300">FY{latest.fiscal_year}</span></div>
                <div className="text-lg font-semibold text-slate-900 font-mono tracking-tight">{fmtEur(latest.ebitda)}</div>
              </div>
              <div className="rounded-xl border border-slate-100 bg-white px-5 py-4">
                <div className="text-xs text-slate-400 mb-1">Margin <span className="font-mono text-slate-300">FY{latest.fiscal_year}</span></div>
                <div className={`text-lg font-semibold font-mono tracking-tight ${marginColor}`}>{fmtPct(latest.ebitda_margin_pct)}</div>
              </div>
              <div className="rounded-xl border border-slate-100 bg-white px-5 py-4">
                <div className="text-xs text-slate-400 mb-1">FTE <span className="font-mono text-slate-300">FY{latest.fiscal_year}</span></div>
                <div className="text-lg font-semibold text-slate-900 font-mono tracking-tight">{latest.fte_total != null ? fmtNumber(latest.fte_total) : "\u2014"}</div>
              </div>
            </div>
          );
        })()}
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={handleTabChange}>
        <TabsList variant="line" className="border-b border-slate-100 gap-0 flex-wrap">
          <TabsTrigger value="summary" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2 data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Summary
          </TabsTrigger>
          <TabsTrigger value="pnl" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2 data-active:text-indigo-600 data-active:after:bg-indigo-600">
            P&L
          </TabsTrigger>
          <TabsTrigger value="cashflow" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2 data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Cash Flow
          </TabsTrigger>
          <TabsTrigger value="balancesheet" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2 data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Balance Sheet
          </TabsTrigger>
          <TabsTrigger value="credit" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2 data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Credit
          </TabsTrigger>
          <TabsTrigger value="administrators" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2 data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Administrators
          </TabsTrigger>
          <TabsTrigger value="structure" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2 data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Structure
          </TabsTrigger>
          <TabsTrigger value="network" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2 data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Network
          </TabsTrigger>
          <TabsTrigger value="publications" className="text-[11px] uppercase tracking-wider font-medium px-3 py-2 data-active:text-indigo-600 data-active:after:bg-indigo-600">
            Publications
          </TabsTrigger>
        </TabsList>

        {/* ===== Summary tab ===== */}
        <TabsContent value="summary" className="mt-6">
          {(() => {
            const sorted = [...(financials?.summary ?? [])].sort((a, b) => b.fiscal_year - a.fiscal_year);
            const latest = sorted[0] ?? null;
            const prev = sorted[1] ?? null;

            const currentAdmins = (structure?.administrators || []).filter(
              (a) => !a.mandate_end || a.mandate_end === "" || new Date(a.mandate_end) > new Date()
            );

            // YoY change helper
            function yoyChange(curr: number | null, previous: number | null): { pct: number; direction: "up" | "down" | "flat" } | null {
              if (curr == null || previous == null || previous === 0) return null;
              const pct = ((curr - previous) / Math.abs(previous)) * 100;
              return { pct, direction: pct > 0.5 ? "up" : pct < -0.5 ? "down" : "flat" };
            }

            function changeArrow(change: { pct: number; direction: "up" | "down" | "flat" } | null, goodIfUp = true) {
              if (!change) return null;
              const isGood = (change.direction === "up" && goodIfUp) || (change.direction === "down" && !goodIfUp);
              const color = change.direction === "flat" ? "text-slate-400" : isGood ? "text-emerald-500" : "text-red-500";
              const arrow = change.direction === "up" ? "\u2191" : change.direction === "down" ? "\u2193" : "\u2192";
              return (
                <span className={`text-xs font-medium ${color}`}>
                  {arrow} {Math.abs(change.pct).toFixed(1)}%
                </span>
              );
            }

            // Credit ratios
            let netDebtEbitda: number | null = null;
            if (latest) {
              const grossDebt = (latest.lt_financial_debt ?? 0) + (latest.st_financial_debt ?? 0);
              const netDebt = grossDebt - (latest.cash ?? 0) - (latest.current_investments ?? 0);
              netDebtEbitda = latest.ebitda && latest.ebitda !== 0 ? netDebt / latest.ebitda : null;
            }

            // Margin color
            function marginColorClass(v: number | null): string {
              if (v == null) return "text-slate-900";
              if (v >= 15) return "text-emerald-600";
              if (v >= 5) return "text-amber-600";
              if (v < 0) return "text-red-600";
              return "text-slate-900";
            }

            // Health pill color
            function pillColor(type: "leverage" | "margin" | "growth", value: number | null): string {
              if (value == null) return "bg-slate-50 text-slate-400 border-slate-100";
              if (type === "leverage") {
                if (value < 3) return "bg-emerald-50 text-emerald-700 border-emerald-100";
                if (value <= 5) return "bg-amber-50 text-amber-700 border-amber-100";
                return "bg-red-50 text-red-700 border-red-100";
              }
              if (type === "margin") {
                if (value >= 15) return "bg-emerald-50 text-emerald-700 border-emerald-100";
                if (value >= 5) return "bg-amber-50 text-amber-700 border-amber-100";
                return "bg-red-50 text-red-700 border-red-100";
              }
              // growth
              if (value > 2) return "bg-emerald-50 text-emerald-700 border-emerald-100";
              if (value >= -2) return "bg-slate-50 text-slate-500 border-slate-100";
              return "bg-red-50 text-red-700 border-red-100";
            }

            const revenueYoy = yoyChange(latest?.revenue ?? null, prev?.revenue ?? null);
            const ebitdaYoy = yoyChange(latest?.ebitda ?? null, prev?.ebitda ?? null);
            const fteYoy = yoyChange(latest?.fte_total ?? null, prev?.fte_total ?? null);

            // Sparkline data (last 5 years)
            const sparkData = sorted.slice(0, 5).reverse().map((r) => ({
              fy: String(r.fiscal_year),
              Revenue: r.revenue,
              EBITDA: r.ebitda,
            }));

            return (
              <div className="space-y-6">
                {/* Row 1: KPIs (left) + Trend chart (right) */}
                {latest && (
                  <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
                    {/* Left: compact KPI list */}
                    <div className="lg:col-span-2 rounded-xl border border-slate-100 bg-white p-4">
                      <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
                        <BarChart3 className="h-3 w-3" /> Key Financials
                        {latest.fiscal_year && <span className="text-slate-300 font-mono">FY{latest.fiscal_year}</span>}
                      </h3>
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 text-xs text-slate-500">
                            <DollarSign className="h-3.5 w-3.5 text-slate-400" /> Revenue
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold text-slate-900 font-mono">{fmtEur(latest.revenue)}</span>
                            {changeArrow(revenueYoy)}
                          </div>
                        </div>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 text-xs text-slate-500">
                            <TrendingUp className="h-3.5 w-3.5 text-slate-400" /> EBITDA
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold text-slate-900 font-mono">{fmtEur(latest.ebitda)}</span>
                            {changeArrow(ebitdaYoy)}
                          </div>
                        </div>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 text-xs text-slate-500">
                            <Percent className="h-3.5 w-3.5 text-slate-400" /> Margin
                          </div>
                          <span className={`text-sm font-semibold font-mono ${marginColorClass(latest.ebitda_margin_pct)}`}>{fmtPct(latest.ebitda_margin_pct)}</span>
                        </div>
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 text-xs text-slate-500">
                            <Users className="h-3.5 w-3.5 text-slate-400" /> Employees
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold text-slate-900 font-mono">{latest.fte_total != null ? fmtNumber(latest.fte_total) : "\u2014"}</span>
                            {changeArrow(fteYoy)}
                          </div>
                        </div>
                      </div>
                      {/* Health pills */}
                      <div className="flex flex-wrap gap-1.5 mt-4 pt-3 border-t border-slate-50">
                        <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${pillColor("leverage", netDebtEbitda)}`}>
                          {netDebtEbitda != null && isFinite(netDebtEbitda) ? `${netDebtEbitda.toFixed(1)}x leverage` : "— leverage"}
                        </span>
                        <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${pillColor("growth", revenueYoy?.pct ?? null)}`}>
                          {revenueYoy ? `${revenueYoy.pct > 0 ? "+" : ""}${revenueYoy.pct.toFixed(0)}% growth` : "— growth"}
                        </span>
                      </div>
                    </div>

                    {/* Right: sparkline chart */}
                    <div className="lg:col-span-3 rounded-xl border border-slate-100 bg-white p-4">
                      <div className="flex items-baseline justify-between mb-2">
                        <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                          <Activity className="h-3 w-3" /> Trend
                        </h3>
                        <button type="button" onClick={() => setActiveTab("pnl")} className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
                          Full P&L →
                        </button>
                      </div>
                      {sparkData.length >= 2 ? (
                        <>
                          <ResponsiveContainer width="100%" height={130}>
                            <LineChart data={sparkData} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
                              <XAxis dataKey="fy" tick={{ fontSize: 10, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                              <YAxis hide />
                              <Tooltip content={<ChartTooltip />} />
                              <Line type="monotone" dataKey="Revenue" stroke="#6366f1" strokeWidth={2} dot={{ r: 2, fill: "#6366f1" }} />
                              <Line type="monotone" dataKey="EBITDA" stroke="#06b6d4" strokeWidth={2} dot={{ r: 2, fill: "#06b6d4" }} strokeDasharray="4 2" />
                            </LineChart>
                          </ResponsiveContainer>
                          <div className="flex items-center gap-4 mt-1">
                            <div className="flex items-center gap-1.5">
                              <span className="inline-block h-0.5 w-4 rounded bg-indigo-500" />
                              <span className="text-[10px] text-slate-400">Revenue</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                              <span className="inline-block h-0.5 w-4 rounded bg-cyan-500" />
                              <span className="text-[10px] text-slate-400">EBITDA</span>
                            </div>
                          </div>
                        </>
                      ) : (
                        <div className="flex items-center justify-center h-[130px] text-xs text-slate-300">Not enough years for a trend</div>
                      )}
                    </div>
                  </div>
                )}

                {/* 5. Financial History Mini Table (last 5 years) */}
                {sorted.length > 1 && (
                  <div className="rounded-xl border border-slate-100 bg-white overflow-hidden">
                    <div className="px-5 pt-4 pb-2">
                      <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">Financial History</h3>
                    </div>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-t border-slate-50">
                          <th className="px-5 py-2 text-left text-slate-400 font-medium">Year</th>
                          <th className="px-3 py-2 text-right text-slate-400 font-medium">Revenue</th>
                          <th className="px-3 py-2 text-right text-slate-400 font-medium">EBITDA</th>
                          <th className="px-3 py-2 text-right text-slate-400 font-medium">Margin</th>
                          <th className="px-3 py-2 text-right text-slate-400 font-medium">Net Profit</th>
                          <th className="px-3 py-2 text-right text-slate-400 font-medium">FTE</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sorted.slice(0, 5).map((r, i) => (
                          <tr key={r.fiscal_year} className={i === 0 ? "bg-indigo-50/30 font-medium" : "border-t border-slate-50"}>
                            <td className="px-5 py-2 font-mono text-slate-700">{r.fiscal_year}</td>
                            <td className="px-3 py-2 text-right font-mono text-slate-700">{fmtEur(r.revenue)}</td>
                            <td className="px-3 py-2 text-right font-mono text-slate-700">{fmtEur(r.ebitda)}</td>
                            <td className={`px-3 py-2 text-right font-mono ${marginColorClass(r.ebitda_margin_pct)}`}>{fmtPct(r.ebitda_margin_pct)}</td>
                            <td className={`px-3 py-2 text-right font-mono ${(r.net_profit ?? 0) < 0 ? "text-red-600" : "text-slate-700"}`}>{fmtEur(r.net_profit)}</td>
                            <td className="px-3 py-2 text-right font-mono text-slate-700">{r.fte_total != null ? fmtNumber(r.fte_total) : "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* 6. Key People + Recent Publications side by side */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {/* Key People */}
                  <div className="rounded-xl border border-slate-100 bg-white p-4">
                    <div className="flex items-baseline justify-between mb-3">
                      <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                        <UserCheck className="h-3 w-3" /> Key People
                        {currentAdmins.length > 0 && <span className="text-slate-300">({currentAdmins.length})</span>}
                      </h3>
                      {currentAdmins.length > 0 && (
                        <button type="button" onClick={() => setActiveTab("administrators")} className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
                          View all →
                        </button>
                      )}
                    </div>
                    {currentAdmins.length === 0 ? (
                      <div className="flex items-center justify-center py-6 text-xs text-slate-300">
                        <Users className="h-4 w-4 mr-2" /> No administrator data
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {currentAdmins.slice(0, 6).map((a, i) => (
                          <div key={`${a.name}-${i}`} className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-50 transition-colors">
                            <div className="h-8 w-8 rounded-full bg-indigo-50 flex items-center justify-center text-[10px] font-bold text-indigo-600 shrink-0">
                              {(a.name || "?").slice(0, 2).toUpperCase()}
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="text-sm text-slate-800 font-medium truncate">{a.name}</div>
                              <div className="flex items-center gap-2 text-[10px] text-slate-400">
                                <span>{a.role_label || a.role || "—"}</span>
                                {a.mandate_start && (
                                  <>
                                    <span className="text-slate-200">·</span>
                                    <span className="flex items-center gap-0.5">
                                      <Calendar className="h-2.5 w-2.5" /> Since {a.mandate_start}
                                    </span>
                                  </>
                                )}
                              </div>
                            </div>
                          </div>
                        ))}
                        {currentAdmins.length > 6 && (
                          <button type="button" onClick={() => setActiveTab("administrators")} className="w-full text-center text-[10px] text-indigo-500 hover:text-indigo-700 py-1 font-medium">
                            + {currentAdmins.length - 6} more people →
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Recent Publications */}
                  <div className="rounded-xl border border-slate-100 bg-white p-4">
                    <div className="flex items-baseline justify-between mb-3">
                      <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                        <Newspaper className="h-3 w-3" /> Recent Publications
                        {(structure?.staatsblad_publications?.length ?? 0) > 0 && (
                          <span className="text-slate-300">({structure?.staatsblad_publications?.length})</span>
                        )}
                      </h3>
                      {(structure?.staatsblad_publications?.length ?? 0) > 0 && (
                        <button type="button" onClick={() => setActiveTab("publications")} className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
                          View all →
                        </button>
                      )}
                    </div>
                    {!structure?.staatsblad_publications?.length ? (
                      <div className="flex items-center justify-center py-6 text-xs text-slate-300">
                        <FileText className="h-4 w-4 mr-2" /> No publications yet
                      </div>
                    ) : (
                      <div className="space-y-1.5">
                        {structure.staatsblad_publications.slice(0, 6).map((pub, i) => (
                          <div key={`pub-${i}`} className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-50 transition-colors">
                            <div className="h-8 w-8 rounded-full bg-slate-50 flex items-center justify-center shrink-0">
                              <FileText className="h-3.5 w-3.5 text-slate-400" />
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="text-xs text-slate-700 truncate">{pub.pub_type || "Publication"}</div>
                              <div className="text-[10px] text-slate-400 flex items-center gap-0.5">
                                <Calendar className="h-2.5 w-2.5" /> {pub.pub_date}
                                {pub.reference && <span className="text-slate-200 ml-1">· #{pub.reference}</span>}
                              </div>
                            </div>
                          </div>
                        ))}
                        {structure.staatsblad_publications.length > 6 && (
                          <button type="button" onClick={() => setActiveTab("publications")} className="w-full text-center text-[10px] text-indigo-500 hover:text-indigo-700 py-1 font-medium">
                            + {structure.staatsblad_publications.length - 6} more →
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {/* Quick navigation links */}
                <div className="flex flex-wrap gap-3 pt-2">
                  {sorted.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setActiveTab("pnl")}
                      className="text-xs text-indigo-500 hover:text-indigo-700 font-medium flex items-center gap-1 transition-colors"
                    >
                      P&L details <ChevronRight className="h-3 w-3" />
                    </button>
                  )}
                  {sorted.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setActiveTab("credit")}
                      className="text-xs text-indigo-500 hover:text-indigo-700 font-medium flex items-center gap-1 transition-colors"
                    >
                      Credit analysis <ChevronRight className="h-3 w-3" />
                    </button>
                  )}
                  {currentAdmins.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setActiveTab("administrators")}
                      className="text-xs text-indigo-500 hover:text-indigo-700 font-medium flex items-center gap-1 transition-colors"
                    >
                      {currentAdmins.length} administrator{currentAdmins.length !== 1 ? "s" : ""} <ChevronRight className="h-3 w-3" />
                    </button>
                  )}
                  {(structure?.shareholders?.length ?? 0) > 0 && (
                    <button
                      type="button"
                      onClick={() => setActiveTab("structure")}
                      className="text-xs text-indigo-500 hover:text-indigo-700 font-medium flex items-center gap-1 transition-colors"
                    >
                      Structure <ChevronRight className="h-3 w-3" />
                    </button>
                  )}
                </div>
              </div>
            );
          })()}
        </TabsContent>

        {/* ===== P&L tab ===== */}
        <TabsContent value="pnl" className="mt-3">
          {!financials || financials.summary.length === 0 ? (
            <div className="py-8 text-center">
              <p className="text-sm text-slate-500 mb-4">No financial data available for this company.</p>
              <Button
                variant="outline"
                disabled={nbbLoading}
                onClick={async () => {
                  setNbbLoading(true);
                  setNbbResult(null);
                  try {
                    const res = await fetch(`/api/companies/${cbe}/load`, { method: "POST" });
                    if (!res.ok) throw new Error(`HTTP ${res.status}`);
                    setNbbResult("success");
                    setTimeout(() => window.location.reload(), 2000);
                  } catch {
                    setNbbResult("error");
                  } finally {
                    setNbbLoading(false);
                  }
                }}
                className={`text-indigo-600 border-indigo-300 hover:bg-indigo-50 ${nbbLoading ? "opacity-70 cursor-not-allowed" : ""}`}
              >
                {nbbLoading ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <Download className="w-4 h-4 mr-2" />
                )}
                {nbbLoading ? "Loading..." : "Load from NBB"}
              </Button>
              {nbbLoading && (
                <p className="mt-3 text-xs text-slate-400 animate-pulse">
                  Loading financial data from NBB... This may take a minute.
                </p>
              )}
              {nbbResult === "success" && (
                <div className="mt-3 flex items-center justify-center gap-1.5 text-xs text-emerald-600">
                  <CheckCircle2 className="w-4 h-4" />
                  Data loaded successfully. Refreshing...
                </div>
              )}
              {nbbResult === "error" && (
                <div className="mt-3 flex items-center justify-center gap-1.5 text-xs text-red-500">
                  <XCircle className="w-4 h-4" />
                  Failed to load data. The company may not have filings available.
                </div>
              )}
            </div>
          ) : (
            <>
              {/* Income statement table */}
              <div className="rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-slate-50">
                      <TableHead>FY</TableHead>
                      <TableHead className="text-right">Revenue</TableHead>
                      <TableHead className="text-right">EBIT</TableHead>
                      <TableHead className="text-right">EBITDA</TableHead>
                      <TableHead className="text-right">Margin %</TableHead>
                      <TableHead className="text-right">Net Profit</TableHead>
                      <TableHead className="text-right">Personnel Costs</TableHead>
                      <TableHead className="text-right">FTE</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {[...financials.summary]
                      .sort((a, b) => b.fiscal_year - a.fiscal_year)
                      .map((row) => (
                        <TableRow key={row.fiscal_year}>
                          <TableCell className="font-medium text-xs py-1.5">
                            {row.fiscal_year}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs py-1.5">
                            {fmtEur(row.revenue)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs py-1.5">
                            {fmtEur(row.ebit)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs py-1.5">
                            {fmtEur(row.ebitda)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs py-1.5">
                            {fmtPct(row.ebitda_margin_pct)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs py-1.5">
                            {fmtEur(row.net_profit)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs py-1.5">
                            {fmtEur(row.personnel_costs)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs py-1.5">
                            {fmtNumber(row.fte_total)}
                          </TableCell>
                        </TableRow>
                      ))}
                  </TableBody>
                </Table>
              </div>

              {/* Revenue & EBITDA Chart */}
              {chartData.length >= 2 && (
                <Card className="mt-4">
                  <CardContent className="pt-3 pb-3">
                    <h3 className="mb-3 text-xs font-semibold text-slate-700">
                      Revenue & EBITDA trend
                    </h3>
                    <ResponsiveContainer width="100%" height={320}>
                      <LineChart data={chartData}>
                        <CartesianGrid
                          strokeDasharray="3 3"
                          stroke="#e2e8f0"
                        />
                        <XAxis
                          dataKey="fy"
                          tick={{ fontSize: 12, fill: "#64748b" }}
                        />
                        <YAxis
                          tick={{ fontSize: 12, fill: "#64748b" }}
                          tickFormatter={(v: number) => fmtEur(v)}
                        />
                        <Tooltip content={<ChartTooltip />} />
                        <Legend
                          wrapperStyle={{ fontSize: "12px" }}
                        />
                        <Line
                          type="monotone"
                          dataKey="Revenue"
                          stroke="#4f46e5"
                          strokeWidth={2}
                          dot={{ r: 4, fill: "#4f46e5" }}
                        />
                        <Line
                          type="monotone"
                          dataKey="EBITDA"
                          stroke="#06b6d4"
                          strokeWidth={2}
                          dot={{ r: 4, fill: "#06b6d4" }}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
              )}
            </>
          )}
        </TabsContent>

        {/* ===== Cash Flow tab ===== */}
        <TabsContent value="cashflow" className="mt-3">
          {!financials || financials.summary.length < 2 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              Need at least two years of financial data to derive cash flow.
            </p>
          ) : (() => {
            const sorted = [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year);

            // Helper: format value, red if negative
            const fmtCell = (v: number | null) => {
              if (v == null) return <span className="text-slate-300">{"\u2014"}</span>;
              const formatted = fmtEur(v);
              return v < 0 ? <span className="text-red-600">{formatted}</span> : <>{formatted}</>;
            };

            const cfRows = sorted.slice(0, -1).map((row, idx) => {
              const prev = sorted[idx + 1];

              const ebitda = row.ebitda;

              // Working capital components
              const invCurr = row.inventories ?? 0;
              const invPrev = prev.inventories ?? 0;
              const recCurr = row.trade_receivables ?? 0;
              const recPrev = prev.trade_receivables ?? 0;
              const payCurr = row.trade_payables ?? 0;
              const payPrev = prev.trade_payables ?? 0;

              const deltaInv = invCurr - invPrev;
              const deltaRec = recCurr - recPrev;
              const deltaPay = payCurr - payPrev;
              // WC change = delta(inv + rec) - delta(pay) -- increase in assets is cash outflow (negative)
              const wcChange = -((deltaInv + deltaRec) - deltaPay);

              // Operating Cash Flow
              const ocf = ebitda != null ? ebitda + wcChange : null;

              // CapEx = delta fixed assets + D&A (always negative outflow)
              const capex = -Math.abs((row.fixed_assets ?? 0) - (prev.fixed_assets ?? 0) + Math.abs(row.da ?? 0));

              // Free Cash Flow
              const fcf = ocf != null ? ocf + capex : null;

              // Net Debt Change
              const grossDebtCurr = (row.lt_financial_debt ?? 0) + (row.st_financial_debt ?? 0);
              const grossDebtPrev = (prev.lt_financial_debt ?? 0) + (prev.st_financial_debt ?? 0);
              const netDebtChange = grossDebtCurr - grossDebtPrev;

              return {
                fiscal_year: row.fiscal_year,
                ebitda,
                wcChange: wcChange !== 0 ? wcChange : null,
                ocf,
                capex: capex !== 0 ? capex : null,
                fcf,
                netDebtChange: netDebtChange !== 0 ? netDebtChange : null,
              };
            });

            type CFLine = {
              label: string;
              key: keyof (typeof cfRows)[0];
              bold?: boolean;
              indent?: boolean;
              topBorder?: boolean;
            };

            const lines: CFLine[] = [
              { label: "EBITDA", key: "ebitda", bold: true },
              { label: "Change in Working Capital", key: "wcChange", indent: true },
              { label: "Operating Cash Flow", key: "ocf", bold: true, topBorder: true },
              { label: "CapEx (est.)", key: "capex", indent: true },
              { label: "Free Cash Flow", key: "fcf", bold: true, topBorder: true },
              { label: "Net Debt Change", key: "netDebtChange", indent: true },
            ];

            return (
              <div>
                <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-cyan-500 pl-2">
                  Derived Cash Flow
                </h3>
                <div className="rounded-lg border overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-slate-50">
                        <TableHead className="text-xs min-w-[220px]">Line Item</TableHead>
                        {cfRows.map((r) => (
                          <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[100px]">
                            FY{r.fiscal_year}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {lines.map((line) => (
                        <TableRow key={line.key} className={line.topBorder ? "border-t-2 border-slate-300" : ""}>
                          <TableCell className={`text-xs py-1 ${line.bold ? "font-bold text-slate-800" : "text-slate-600"} ${line.indent ? "pl-8" : ""}`}>
                            {line.indent ? <span className="text-slate-300 mr-1">{line.key === "netDebtChange" ? "\u2514" : "\u2514"}</span> : null}
                            {line.label}
                          </TableCell>
                          {cfRows.map((r) => (
                            <TableCell
                              key={r.fiscal_year}
                              className={`text-right font-mono text-xs py-1 ${line.bold ? "font-bold" : ""}`}
                            >
                              {fmtCell(r[line.key] as number | null)}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                <p className="mt-1 text-[10px] text-slate-400 italic">
                  Working capital = inventories + trade receivables - trade payables. Increase in WC is a cash outflow (shown negative).
                  CapEx estimated as delta fixed assets + D&A. Free Cash Flow = Operating Cash Flow + CapEx.
                </p>
              </div>
            );
          })()}
        </TabsContent>

        {/* ===== Balance Sheet tab ===== */}
        <TabsContent value="balancesheet" className="mt-3">
          {!financials || financials.summary.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              No financial data available for this company.
            </p>
          ) : (() => {
            const sorted = [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year);

            // Helper: format value, red if negative
            const fmtCell = (v: number | null) => {
              if (v == null) return <span className="text-slate-300">{"\u2014"}</span>;
              const formatted = fmtEur(v);
              return v < 0 ? <span className="text-red-600">{formatted}</span> : <>{formatted}</>;
            };

            // Build derived rows per year
            const bsRows = sorted.map((row) => {
              const fixedAssets = row.fixed_assets ?? null;
              const totalAssets = row.total_assets ?? null;
              const currentAssets = totalAssets != null && fixedAssets != null ? totalAssets - fixedAssets : null;
              const inventories = row.inventories ?? null;
              const tradeReceivables = row.trade_receivables ?? null;
              const cash = row.cash ?? null;
              const currentInvestments = row.current_investments ?? null;
              const cashAndInv = cash != null || currentInvestments != null ? (cash ?? 0) + (currentInvestments ?? 0) : null;
              const knownCurrentItems = (inventories ?? 0) + (tradeReceivables ?? 0) + (cashAndInv ?? 0);
              const otherCurrentAssets = currentAssets != null ? currentAssets - knownCurrentItems : null;

              const equity = row.equity ?? null;
              const ltDebt = row.lt_financial_debt ?? null;
              const stFinDebt = row.st_financial_debt ?? null;
              const tradePayables = row.trade_payables ?? null;
              // Short-term debt (total) = Total L&E - Equity - LT Debt
              const totalLE = totalAssets; // must balance
              const stDebtTotal = totalLE != null && equity != null && ltDebt != null
                ? totalLE - equity - ltDebt
                : null;

              return {
                fiscal_year: row.fiscal_year,
                fixedAssets,
                currentAssets,
                inventories,
                tradeReceivables,
                cashAndInv,
                otherCurrentAssets: otherCurrentAssets != null && Math.abs(otherCurrentAssets) > 0.5 ? otherCurrentAssets : null,
                totalAssets,
                equity,
                ltDebt,
                ltFinDebt: ltDebt, // rubric 170/4
                stDebtTotal,
                stFinDebt,
                tradePayables,
                totalLE: totalAssets,
              };
            });

            // Row definition: { label, key, bold?, indent?, separator? }
            type BSLine = {
              label: string;
              key: keyof (typeof bsRows)[0];
              bold?: boolean;
              indent?: boolean;
              topBorder?: boolean;
              sectionHeader?: boolean;
            };

            const assetLines: BSLine[] = [
              { label: "Fixed Assets (20/28)", key: "fixedAssets", indent: false },
              { label: "Current Assets", key: "currentAssets", indent: false },
              { label: "Inventories (3)", key: "inventories", indent: true },
              { label: "Trade Receivables (40/41)", key: "tradeReceivables", indent: true },
              { label: "Cash & Short-term Inv. (50/58)", key: "cashAndInv", indent: true },
              { label: "Other Current Assets", key: "otherCurrentAssets", indent: true },
              { label: "Total Assets (20/58)", key: "totalAssets", bold: true, topBorder: true },
            ];

            const liabLines: BSLine[] = [
              { label: "Equity (10/15)", key: "equity", indent: false },
              { label: "Long-term Debt (17)", key: "ltDebt", indent: false },
              { label: "of which: Financial Debt (170/4)", key: "ltFinDebt", indent: true },
              { label: "Short-term Debt", key: "stDebtTotal", indent: false },
              { label: "of which: Financial Debt (43)", key: "stFinDebt", indent: true },
              { label: "Trade Payables (44)", key: "tradePayables", indent: true },
              { label: "Total Liabilities + Equity", key: "totalLE", bold: true, topBorder: true },
            ];

            return (
              <div>
                <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2">
                  Balance Sheet
                </h3>
                <div className="rounded-lg border overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-slate-50">
                        <TableHead className="text-xs min-w-[220px]">Line Item</TableHead>
                        {bsRows.map((r) => (
                          <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[100px]">
                            FY{r.fiscal_year}
                          </TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {/* Assets section header */}
                      <TableRow className="bg-slate-50/50">
                        <TableCell className="text-xs font-bold text-slate-700 py-1" colSpan={bsRows.length + 1}>
                          Assets
                        </TableCell>
                      </TableRow>
                      {assetLines.map((line) => (
                        <TableRow key={line.key} className={line.topBorder ? "border-t-2 border-slate-300" : ""}>
                          <TableCell className={`text-xs py-1 ${line.bold ? "font-bold text-slate-800" : "text-slate-600"} ${line.indent ? "pl-8" : ""}`}>
                            {line.indent && !line.bold ? <span className="text-slate-300 mr-1">{"\u2514"}</span> : null}
                            {line.label}
                          </TableCell>
                          {bsRows.map((r) => (
                            <TableCell
                              key={r.fiscal_year}
                              className={`text-right font-mono text-xs py-1 ${line.bold ? "font-bold" : ""}`}
                            >
                              {fmtCell(r[line.key] as number | null)}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                      {/* Liabilities & Equity section header */}
                      <TableRow className="bg-slate-50/50">
                        <TableCell className="text-xs font-bold text-slate-700 py-1 pt-3" colSpan={bsRows.length + 1}>
                          Liabilities & Equity
                        </TableCell>
                      </TableRow>
                      {liabLines.map((line) => (
                        <TableRow key={line.key + "_liab"} className={line.topBorder ? "border-t-2 border-slate-300" : ""}>
                          <TableCell className={`text-xs py-1 ${line.bold ? "font-bold text-slate-800" : "text-slate-600"} ${line.indent ? "pl-8" : ""}`}>
                            {line.indent && !line.bold ? <span className="text-slate-300 mr-1">{"\u2514"}</span> : null}
                            {line.label}
                          </TableCell>
                          {bsRows.map((r) => (
                            <TableCell
                              key={r.fiscal_year}
                              className={`text-right font-mono text-xs py-1 ${line.bold ? "font-bold" : ""}`}
                            >
                              {fmtCell(r[line.key] as number | null)}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                <p className="mt-1 text-[10px] text-slate-400 italic">
                  Rubric references in parentheses per Belgian GAAP. Short-term debt = Total L&E - Equity - LT Debt. Other Current Assets = Current Assets - Inventories - Receivables - Cash.
                </p>
              </div>
            );
          })()}
        </TabsContent>

        {/* ===== Administrators tab ===== */}
        <TabsContent value="administrators" className="mt-3">
          {(() => {
            const currentAdmins = (structure?.administrators || []).filter(
              (a) => !a.mandate_end || a.mandate_end === "" || new Date(a.mandate_end) > new Date()
            );
            const pastAdmins = (structure?.administrators || []).filter(
              (a) => a.mandate_end && a.mandate_end !== "" && new Date(a.mandate_end) <= new Date()
            );

            if (currentAdmins.length === 0 && pastAdmins.length === 0) {
              return (
                <p className="py-8 text-center text-sm text-slate-500">
                  No administrator data available for this company.
                </p>
              );
            }

            return (
              <div className="space-y-4">
                {/* Current Administrators */}
                {currentAdmins.length > 0 && (
                  <div>
                    <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-green-500 pl-2">
                      Current Administrators ({currentAdmins.length})
                    </h3>
                    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                      {currentAdmins.map((admin, i) => {
                        const adminCbe = cleanCbe(admin.identifier);
                        return (
                          <Card key={`current-${admin.name}-${admin.role}-${i}`}>
                            <CardContent className="p-3">
                              <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-green-500" />
                                    {adminCbe ? (
                                      <Link
                                        href={`/company/${adminCbe}`}
                                        className="font-bold text-sm text-indigo-600 hover:underline truncate"
                                      >
                                        {admin.name}
                                      </Link>
                                    ) : (
                                      <span className="font-bold text-sm text-slate-900 truncate">
                                        {admin.name}
                                      </span>
                                    )}
                                  </div>
                                  <p className="mt-1 text-sm font-medium text-slate-700">
                                    {admin.role_label}
                                  </p>
                                  {admin.mandate_start && (
                                    <p className="mt-1 text-xs text-slate-500">
                                      Since {admin.mandate_start}
                                    </p>
                                  )}
                                  {adminCbe && (
                                    <p className="mt-1 text-xs text-slate-400 font-mono">
                                      {fmtCbe(adminCbe)}
                                    </p>
                                  )}
                                </div>
                                <Badge
                                  variant="secondary"
                                  className="text-[10px] shrink-0 bg-green-50 text-green-700 border-green-200"
                                >
                                  Active
                                </Badge>
                              </div>
                            </CardContent>
                          </Card>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Past Administrators */}
                {pastAdmins.length > 0 && (
                  <div>
                    <button
                      type="button"
                      className="mb-3 flex items-center gap-1 text-xs font-bold uppercase tracking-wider text-slate-400 border-l-[3px] border-slate-300 pl-2 hover:text-slate-600 transition-colors"
                      onClick={(e) => {
                        const content = (e.currentTarget as HTMLElement).nextElementSibling;
                        const chevron = (e.currentTarget as HTMLElement).querySelector('[data-chevron]');
                        if (content) {
                          content.classList.toggle("hidden");
                        }
                        if (chevron) {
                          chevron.classList.toggle("rotate-180");
                        }
                      }}
                    >
                      Past Administrators ({pastAdmins.length})
                      <ChevronDown data-chevron className="h-3.5 w-3.5 transition-transform" />
                    </button>
                    <div className="hidden">
                      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                        {pastAdmins.map((admin, i) => {
                          const adminCbe = cleanCbe(admin.identifier);
                          return (
                            <Card key={`past-${admin.name}-${admin.role}-${i}`} className="opacity-75">
                              <CardContent className="p-3">
                                <div className="flex items-start justify-between gap-2">
                                  <div className="min-w-0">
                                    <div className="flex items-center gap-2">
                                      <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-slate-300" />
                                      {adminCbe ? (
                                        <Link
                                          href={`/company/${adminCbe}`}
                                          className="font-bold text-sm text-slate-500 hover:underline truncate"
                                        >
                                          {admin.name}
                                        </Link>
                                      ) : (
                                        <span className="font-bold text-sm text-slate-500 truncate">
                                          {admin.name}
                                        </span>
                                      )}
                                    </div>
                                    <p className="mt-1 text-sm text-slate-500">
                                      {admin.role_label}
                                    </p>
                                    <p className="mt-1 text-xs text-slate-400">
                                      {admin.mandate_start ?? "?"} - {admin.mandate_end}
                                    </p>
                                    {adminCbe && (
                                      <p className="mt-1 text-xs text-slate-400 font-mono">
                                        {fmtCbe(adminCbe)}
                                      </p>
                                    )}
                                  </div>
                                  <Badge
                                    variant="secondary"
                                    className="text-[10px] shrink-0 bg-slate-50 text-slate-400 border-slate-200"
                                  >
                                    Ended
                                  </Badge>
                                </div>
                              </CardContent>
                            </Card>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
        </TabsContent>

        {/* ===== Structure tab ===== */}
        <TabsContent value="structure" className="mt-3">
          {!structure ||
          (structure.shareholders.length === 0 &&
            structure.participating_interests.length === 0) ? (
            <p className="py-8 text-center text-sm text-slate-500">
              No structure data available for this company.
            </p>
          ) : (
            <div className="grid gap-3 lg:grid-cols-2">
              {/* Left column: collapsible cards */}
              <div className="space-y-3">
                  {/* Shareholders (collapsible) */}
                  {structure.shareholders.length > 0 && (
                    <Card>
                      <CardContent>
                        <button
                          type="button"
                          onClick={(e) => {
                            const content = (e.currentTarget as HTMLElement).nextElementSibling;
                            const chevron = (e.currentTarget as HTMLElement).querySelector('[data-chevron]');
                            if (content) content.classList.toggle("hidden");
                            if (chevron) chevron.classList.toggle("rotate-180");
                          }}
                          className="w-full flex items-center justify-between mb-2"
                        >
                          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-green-500 pl-2">
                            Shareholders ({structure.shareholders.length})
                          </h3>
                          <ChevronDown data-chevron className="h-4 w-4 text-slate-400 transition-transform" />
                        </button>
                        <div className="space-y-1.5">
                          {structure.shareholders.map((sh, i) => {
                            const shCbe = cleanCbe(sh.identifier);
                            return (
                              <div
                                key={`${sh.name}-${i}`}
                                className="rounded-md border px-3 py-2"
                              >
                                <div className="flex items-center justify-between gap-2">
                                  {shCbe ? (
                                    <Link
                                      href={`/company/${shCbe}`}
                                      className="font-semibold text-sm text-indigo-600 hover:underline"
                                    >
                                      {sh.name}
                                    </Link>
                                  ) : (
                                    <span className="font-semibold text-sm text-slate-900">
                                      {sh.name}
                                    </span>
                                  )}
                                  <div className="flex items-center gap-2 shrink-0">
                                    {sh.ownership_pct != null && (
                                      <span className="font-mono text-xs font-medium text-slate-700">
                                        {sh.ownership_pct.toFixed(1)}%
                                      </span>
                                    )}
                                    {sh.shareholder_type && (
                                      <Badge
                                        variant="secondary"
                                        className="text-[10px]"
                                      >
                                        {sh.shareholder_type}
                                      </Badge>
                                    )}
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </CardContent>
                    </Card>
                  )}

                  {/* Participating Interests (collapsible) */}
                  {structure.participating_interests.length > 0 && (
                    <Card>
                      <CardContent>
                        <button
                          type="button"
                          onClick={(e) => {
                            const content = (e.currentTarget as HTMLElement).nextElementSibling;
                            const chevron = (e.currentTarget as HTMLElement).querySelector('[data-chevron]');
                            if (content) content.classList.toggle("hidden");
                            if (chevron) chevron.classList.toggle("rotate-180");
                          }}
                          className="w-full flex items-center justify-between mb-2"
                        >
                          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-orange-500 pl-2">
                            Participating Interests ({structure.participating_interests.length})
                          </h3>
                          <ChevronDown data-chevron className="h-4 w-4 text-slate-400 transition-transform" />
                        </button>
                        <div className="space-y-1.5">
                          {structure.participating_interests.map((pi, i) => {
                            const piCbe = cleanCbe(pi.identifier);
                            return (
                              <div
                                key={`${pi.name}-${i}`}
                                className="rounded-md border px-3 py-2"
                              >
                                <div className="flex items-center justify-between gap-2">
                                  {piCbe ? (
                                    <Link
                                      href={`/company/${piCbe}`}
                                      className="font-semibold text-sm text-indigo-600 hover:underline"
                                    >
                                      {pi.name}
                                    </Link>
                                  ) : (
                                    <span className="font-semibold text-sm text-slate-900">
                                      {pi.name}
                                    </span>
                                  )}
                                  <div className="flex items-center gap-2 shrink-0">
                                    {pi.ownership_pct != null && (
                                      <span className="font-mono text-xs font-medium text-slate-700">
                                        {pi.ownership_pct.toFixed(1)}%
                                      </span>
                                    )}
                                    {pi.country && (
                                      <Badge
                                        variant="secondary"
                                        className="text-[10px]"
                                      >
                                        {pi.country}
                                      </Badge>
                                    )}
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </CardContent>
                    </Card>
                  )}
              </div>

              {/* Right column: visual timelines */}
              <div className="space-y-3">
                {/* Shareholder Timeline */}
                {structure.shareholders.filter(sh => sh.fiscal_year).length > 0 && (
                  <Card>
                    <CardContent className="pt-3 pb-3">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-green-500 pl-2 mb-3">
                        Shareholder Timeline
                      </h3>
                      <div className="relative pl-6">
                        <div className="absolute left-2 top-0 bottom-0 w-px bg-green-200" />
                        {structure.shareholders
                          .filter(sh => sh.fiscal_year)
                          .sort((a, b) => String(b.fiscal_year).localeCompare(String(a.fiscal_year)))
                          .map((sh, i) => (
                            <div key={i} className="relative mb-3 last:mb-0">
                              <div className="absolute -left-4 top-1 w-2.5 h-2.5 rounded-full bg-green-500 border-2 border-white" />
                              <div className="text-xs font-mono text-slate-400 mb-0.5">{sh.fiscal_year}</div>
                              <div className="text-sm font-medium text-slate-900">{sh.name}</div>
                              {sh.ownership_pct != null && (
                                <div className="text-xs text-slate-500">{sh.ownership_pct}% ownership</div>
                              )}
                            </div>
                          ))}
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Subsidiary Timeline */}
                {structure.participating_interests.filter(pi => pi.fiscal_year).length > 0 && (
                  <Card>
                    <CardContent className="pt-3 pb-3">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-orange-500 pl-2 mb-3">
                        Subsidiary Timeline
                      </h3>
                      <div className="relative pl-6">
                        <div className="absolute left-2 top-0 bottom-0 w-px bg-orange-200" />
                        {structure.participating_interests
                          .filter(pi => pi.fiscal_year)
                          .sort((a, b) => String(b.fiscal_year).localeCompare(String(a.fiscal_year)))
                          .map((pi, i) => (
                            <div key={i} className="relative mb-3 last:mb-0">
                              <div className="absolute -left-4 top-1 w-2.5 h-2.5 rounded-full bg-orange-500 border-2 border-white" />
                              <div className="text-xs font-mono text-slate-400 mb-0.5">{pi.fiscal_year}</div>
                              <div className="text-sm font-medium text-slate-900">{pi.name}</div>
                              {pi.ownership_pct != null && (
                                <div className="text-xs text-slate-500">{pi.ownership_pct}% ownership</div>
                              )}
                            </div>
                          ))}
                      </div>
                    </CardContent>
                  </Card>
                )}
              </div>
            </div>
          )}
        </TabsContent>

        {/* ===== Network tab ===== */}
        <TabsContent value="network" className="mt-3">
          <NetworkGraph cbe={cbe} companyName={detail?.name || cbe} />
        </TabsContent>

        {/* ===== Credit Analysis tab ===== */}
        <TabsContent value="credit" className="mt-3">
          {!financials || financials.summary.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              No financial data available for credit analysis.
            </p>
          ) : (() => {
            const sorted = [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year);

            // Compute ratios for each year
            const ratios = sorted.map((row) => {
              const grossDebt = (row.lt_financial_debt ?? 0) + (row.st_financial_debt ?? 0);
              const netDebt = grossDebt - (row.cash ?? 0) - (row.current_investments ?? 0);
              const ebitda = row.ebitda;
              const ebit = row.ebit;
              const equity = row.equity;
              const netProfit = row.net_profit;
              const revenue = row.revenue;
              const finCharges = row.financial_charges;
              const tradeRec = row.trade_receivables;
              const tradePay = row.trade_payables;
              const stDebt = row.st_financial_debt;

              const netDebtEbitda = ebitda && ebitda !== 0 ? netDebt / ebitda : null;
              const debtEquity = equity && equity !== 0 ? grossDebt / equity : null;
              const interestCoverage = finCharges && finCharges !== 0 ? (ebit ?? 0) / Math.abs(finCharges) : null;
              const cashStDebt = stDebt && stDebt !== 0 ? ((row.cash ?? 0) + (row.current_investments ?? 0)) / stDebt : null;
              const roe = equity && equity !== 0 ? ((netProfit ?? 0) / equity) * 100 : null;
              const ebitdaMargin = revenue && revenue > 0 ? ((ebitda ?? 0) / revenue) * 100 : null;
              const dso = revenue && revenue > 0 ? ((tradeRec ?? 0) / revenue) * 365 : null;
              const dpo = revenue && revenue > 0 ? ((tradePay ?? 0) / revenue) * 365 : null;

              return {
                fiscal_year: row.fiscal_year,
                netDebtEbitda,
                debtEquity,
                interestCoverage,
                cashStDebt,
                roe,
                ebitdaMargin,
                dso,
                dpo,
                netDebt,
                grossDebt,
              };
            });

            const latest = ratios[0];

            // Color thresholds
            function leverageColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v < 3) return "bg-green-50 border-green-200 text-green-800";
              if (v <= 5) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }
            function debtEquityColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v < 1) return "bg-green-50 border-green-200 text-green-800";
              if (v <= 2) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }
            function coverageColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v >= 3) return "bg-green-50 border-green-200 text-green-800";
              if (v >= 1.5) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }
            function cashRatioColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v >= 1) return "bg-green-50 border-green-200 text-green-800";
              if (v >= 0.5) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }
            function marginColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v >= 15) return "bg-green-50 border-green-200 text-green-800";
              if (v >= 8) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }
            function roeColor(v: number | null): string {
              if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
              if (v >= 15) return "bg-green-50 border-green-200 text-green-800";
              if (v >= 8) return "bg-amber-50 border-amber-200 text-amber-800";
              return "bg-red-50 border-red-200 text-red-800";
            }
            function fmtRatio(v: number | null, suffix = "x"): string {
              if (v == null || !isFinite(v)) return "\u2014";
              return `${v.toFixed(1)}${suffix}`;
            }
            function fmtDays(v: number | null): string {
              if (v == null || !isFinite(v)) return "\u2014";
              return `${Math.round(v)}d`;
            }

            const metricCards = [
              { label: "Net Debt / EBITDA", value: fmtRatio(latest.netDebtEbitda), colorFn: leverageColor, raw: latest.netDebtEbitda },
              { label: "Debt / Equity", value: fmtRatio(latest.debtEquity), colorFn: debtEquityColor, raw: latest.debtEquity },
              { label: "Interest Coverage", value: fmtRatio(latest.interestCoverage), colorFn: coverageColor, raw: latest.interestCoverage },
              { label: "Cash / ST Debt", value: fmtRatio(latest.cashStDebt), colorFn: cashRatioColor, raw: latest.cashStDebt },
              { label: "EBITDA Margin", value: fmtRatio(latest.ebitdaMargin, "%"), colorFn: marginColor, raw: latest.ebitdaMargin },
              { label: "ROE", value: fmtRatio(latest.roe, "%"), colorFn: roeColor, raw: latest.roe },
            ];

            return (
              <div className="space-y-6">
                {/* Key Metrics Cards */}
                <div>
                  <h3 className="mb-3 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-purple-500 pl-2">
                    Key Ratios (FY{latest.fiscal_year})
                  </h3>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
                    {metricCards.map((m) => (
                      <div
                        key={m.label}
                        className={`rounded-lg border p-3 text-center ${m.colorFn(m.raw)}`}
                      >
                        <div className="text-[10px] font-medium uppercase tracking-wider opacity-70">{m.label}</div>
                        <div className="mt-1 text-lg font-bold">{m.value}</div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Leverage Ratios Table */}
                <div>
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-red-500 pl-2">
                    Leverage
                  </h3>
                  <div className="rounded-lg border overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-slate-50">
                          <TableHead className="text-xs min-w-[160px]">Metric</TableHead>
                          {ratios.map((r) => (
                            <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[90px]">FY{r.fiscal_year}</TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">Net Debt / EBITDA</TableCell>
                          {ratios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.netDebtEbitda)}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">Debt / Equity</TableCell>
                          {ratios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.debtEquity)}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">Interest Coverage</TableCell>
                          {ratios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.interestCoverage)}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">Net Debt</TableCell>
                          {ratios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(r.netDebt)}</TableCell>
                          ))}
                        </TableRow>
                      </TableBody>
                    </Table>
                  </div>
                </div>

                {/* Liquidity */}
                <div>
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-amber-500 pl-2">
                    Liquidity
                  </h3>
                  <div className="rounded-lg border overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-slate-50">
                          <TableHead className="text-xs min-w-[160px]">Metric</TableHead>
                          {ratios.map((r) => (
                            <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[90px]">FY{r.fiscal_year}</TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">Cash / ST Debt</TableCell>
                          {ratios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.cashStDebt)}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">Cash & Investments</TableCell>
                          {sorted.map((row) => (
                            <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">
                              {fmtEur(((row.cash ?? 0) + (row.current_investments ?? 0)) || null)}
                            </TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">ST Financial Debt</TableCell>
                          {sorted.map((row) => (
                            <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(row.st_financial_debt)}</TableCell>
                          ))}
                        </TableRow>
                      </TableBody>
                    </Table>
                  </div>
                </div>

                {/* Profitability */}
                <div>
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-green-500 pl-2">
                    Profitability
                  </h3>
                  <div className="rounded-lg border overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-slate-50">
                          <TableHead className="text-xs min-w-[160px]">Metric</TableHead>
                          {ratios.map((r) => (
                            <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[90px]">FY{r.fiscal_year}</TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">EBITDA Margin</TableCell>
                          {ratios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.ebitdaMargin, "%")}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">ROE</TableCell>
                          {ratios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.roe, "%")}</TableCell>
                          ))}
                        </TableRow>
                      </TableBody>
                    </Table>
                  </div>
                </div>

                {/* Working Capital */}
                <div>
                  <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-blue-500 pl-2">
                    Working Capital
                  </h3>
                  <div className="rounded-lg border overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow className="bg-slate-50">
                          <TableHead className="text-xs min-w-[160px]">Metric</TableHead>
                          {ratios.map((r) => (
                            <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[90px]">FY{r.fiscal_year}</TableHead>
                          ))}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">DSO (days)</TableCell>
                          {ratios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtDays(r.dso)}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">DPO (days)</TableCell>
                          {ratios.map((r) => (
                            <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtDays(r.dpo)}</TableCell>
                          ))}
                        </TableRow>
                        <TableRow>
                          <TableCell className="text-xs text-slate-600 py-1">Cash Conversion (DSO - DPO)</TableCell>
                          {ratios.map((r) => {
                            const ccc = r.dso != null && r.dpo != null ? r.dso - r.dpo : null;
                            return (
                              <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtDays(ccc)}</TableCell>
                            );
                          })}
                        </TableRow>
                      </TableBody>
                    </Table>
                  </div>
                </div>

                <p className="text-[10px] text-slate-400 italic">
                  Thresholds: Net Debt/EBITDA &lt;3x green, 3-5x amber, &gt;5x red. Interest Coverage &gt;3x green, 1.5-3x amber, &lt;1.5x red.
                </p>
              </div>
            );
          })()}
        </TabsContent>

        {/* ===== Publications tab ===== */}
        <TabsContent value="publications" className="mt-3">
          {!structure ||
          structure.staatsblad_publications.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              No Staatsblad publications available.
            </p>
          ) : (
            <div className="space-y-2">
              {structure.staatsblad_publications.map((pub, i) => {
                const typeInfo = pub.pub_type
                  ? PUB_TYPE_MAP[pub.pub_type.toUpperCase()] ??
                    Object.entries(PUB_TYPE_MAP).find(([key]) =>
                      pub.pub_type!.toUpperCase().includes(key)
                    )?.[1] ??
                    null
                  : null;

                return (
                  <Card key={`${pub.pub_date}-${i}`}>
                    <CardContent className="p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-semibold text-slate-900">
                              {pub.pub_date}
                            </span>
                            {typeInfo ? (
                              <span
                                className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold ${typeInfo.color}`}
                              >
                                {typeInfo.label}
                              </span>
                            ) : pub.pub_type ? (
                              <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold bg-slate-100 text-slate-600">
                                {pub.pub_type}
                              </span>
                            ) : null}
                          </div>
                          <p className="mt-1 text-sm text-slate-600">
                            {typeInfo
                              ? typeInfo.summary
                              : pub.pub_type ?? "Publication in the Belgian Official Gazette"}
                          </p>
                          {pub.reference && (
                            <p className="mt-0.5 text-xs text-slate-400">
                              Ref: {pub.reference}
                            </p>
                          )}
                        </div>
                        {pub.pdf_url && (
                          <a
                            href={
                              pub.pdf_url.startsWith("http")
                                ? pub.pdf_url
                                : `https://www.ejustice.just.fgov.be${pub.pdf_url}`
                            }
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 shrink-0 rounded-md border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-600 hover:bg-indigo-100 transition-colors"
                          >
                            View PDF
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
