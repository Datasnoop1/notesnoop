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
import {
  Star,
  ArrowLeft,
  ExternalLink,
  ChevronDown,
  TrendingUp,
  Users,
  Network,
  GitBranch,
  FileText,
  Download,
  Shield,
  Building2,
  MapPin,
  Factory,
  Globe,
  Calendar,
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
  const [activeTab, setActiveTab] = useState("financials");

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

      {/* ━━━ Company Header (health-dashboard inspired) ━━━ */}
      <div className="mb-5 rounded-xl overflow-hidden shadow-lg border border-slate-200">
        {/* Dark header band */}
        <div className="bg-slate-900 px-6 py-5">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <Building2 className="h-7 w-7 text-indigo-400 shrink-0" />
              <h1 className="text-2xl font-bold text-white tracking-tight">
                {detail.name || fmtCbe(cbe)}
              </h1>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Button
                variant="ghost"
                size="icon"
                onClick={toggleFavourite}
                title={isFavourite ? "Remove from favourites" : "Add to favourites"}
                className="hover:bg-white/10"
              >
                <Star
                  className={`h-5 w-5 ${
                    isFavourite
                      ? "fill-yellow-400 text-yellow-500"
                      : "text-slate-400"
                  }`}
                />
              </Button>
              {detail.status === "AC" ? (
                <Badge className="bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/20">
                  Active
                </Badge>
              ) : (
                <Badge className="bg-red-500/20 text-red-300 border border-red-500/30 hover:bg-red-500/20">
                  Ceased
                </Badge>
              )}
            </div>
          </div>
          {/* Info pills */}
          <div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate-400">
            <span className="font-mono text-slate-300">{fmtCbe(cbe)}</span>
            {detail.jf_label && (
              <>
                <span className="text-slate-600">·</span>
                <span>{detail.jf_label}</span>
              </>
            )}
            {detail.start_date && (
              <>
                <span className="text-slate-600">·</span>
                <Calendar className="h-3.5 w-3.5 inline -mt-0.5" />
                <span>Founded {detail.start_date.slice(0, 4)}</span>
              </>
            )}
          </div>
        </div>

        {/* Detail rows */}
        <div className="bg-slate-50 px-6 py-3 space-y-1 border-b border-slate-200">
          {address && (
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <MapPin className="h-3.5 w-3.5 text-slate-400 shrink-0" />
              <span>{address}</span>
            </div>
          )}
          {detail.nace_code && (
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <Factory className="h-3.5 w-3.5 text-slate-400 shrink-0" />
              <span>
                NACE {detail.nace_code}
                {detail.nace_label && detail.nace_label !== detail.nace_code && ` \u2014 ${detail.nace_label}`}
              </span>
            </div>
          )}
          {detail.website && (
            <div className="flex items-center gap-2 text-sm">
              <Globe className="h-3.5 w-3.5 text-slate-400 shrink-0" />
              <a
                href={detail.website.startsWith("http") ? detail.website : `https://${detail.website}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-indigo-600 hover:text-indigo-800 hover:underline"
              >
                {detail.website.replace(/^https?:\/\//, "")}
              </a>
            </div>
          )}
        </div>

        {/* KPI summary bar */}
        {(() => {
          const latest = financials?.summary?.length
            ? [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year)[0]
            : null;
          if (!latest) return null;

          const marginVal = latest.ebitda_margin_pct;
          const marginColorClass =
            marginVal == null
              ? "text-slate-500"
              : marginVal >= 10
                ? "text-emerald-600"
                : marginVal >= 5
                  ? "text-amber-600"
                  : marginVal < 0
                    ? "text-red-600"
                    : "text-slate-600";

          return (
            <div className="grid grid-cols-2 sm:grid-cols-5 divide-x divide-slate-200 bg-white">
              <div className="px-5 py-3 text-center">
                <div className="text-lg font-bold text-slate-900 tracking-tight">
                  {fmtEur(latest.revenue)}
                </div>
                <div className="text-[10px] uppercase tracking-widest text-slate-400 font-medium mt-0.5">Revenue</div>
              </div>
              <div className="px-5 py-3 text-center">
                <div className="text-lg font-bold text-slate-900 tracking-tight">
                  {fmtEur(latest.ebitda)}
                </div>
                <div className="text-[10px] uppercase tracking-widest text-slate-400 font-medium mt-0.5">EBITDA</div>
              </div>
              <div className="px-5 py-3 text-center">
                <div className={`text-lg font-bold tracking-tight ${marginColorClass}`}>
                  {fmtPct(latest.ebitda_margin_pct)}
                </div>
                <div className="text-[10px] uppercase tracking-widest text-slate-400 font-medium mt-0.5">Margin</div>
              </div>
              <div className="px-5 py-3 text-center">
                <div className="text-lg font-bold text-slate-900 tracking-tight">
                  {latest.fte_total != null ? fmtNumber(latest.fte_total) : "\u2014"}
                </div>
                <div className="text-[10px] uppercase tracking-widest text-slate-400 font-medium mt-0.5">FTE</div>
              </div>
              <div className="px-5 py-3 text-center col-span-2 sm:col-span-1">
                <div className="text-lg font-bold text-indigo-600 tracking-tight">
                  FY{latest.fiscal_year}
                </div>
                <div className="text-[10px] uppercase tracking-widest text-slate-400 font-medium mt-0.5">Latest</div>
              </div>
            </div>
          );
        })()}
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={handleTabChange}>
        <TabsList>
          <TabsTrigger value="financials">
            <TrendingUp className="w-4 h-4 mr-1.5" />
            Financials
          </TabsTrigger>
          <TabsTrigger value="administrators">
            <Users className="w-4 h-4 mr-1.5" />
            Administrators
          </TabsTrigger>
          <TabsTrigger value="structure">
            <Network className="w-4 h-4 mr-1.5" />
            Structure
          </TabsTrigger>
          <TabsTrigger value="network">
            <GitBranch className="w-4 h-4 mr-1.5" />
            Network
          </TabsTrigger>
          <TabsTrigger value="credit">
            <Shield className="w-4 h-4 mr-1.5" />
            Credit
          </TabsTrigger>
          <TabsTrigger value="publications">
            <FileText className="w-4 h-4 mr-1.5" />
            Publications
          </TabsTrigger>
        </TabsList>

        {/* ===== Financials tab ===== */}
        <TabsContent value="financials" className="mt-3">
          {!financials || financials.summary.length === 0 ? (
            <div className="py-8 text-center">
              <p className="text-sm text-slate-500 mb-4">No financial data available for this company.</p>
              <Button
                variant="outline"
                onClick={async () => {
                  try {
                    await fetch(`/api/companies/${cbe}/load`, { method: "POST" });
                    // Reload after a delay
                    setTimeout(() => window.location.reload(), 2000);
                  } catch {}
                }}
                className="text-indigo-600 border-indigo-300 hover:bg-indigo-50"
              >
                <Download className="w-4 h-4 mr-2" />
                Load from NBB
              </Button>
            </div>
          ) : (
            <>
              {/* Financial summary table */}
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
                      <TableHead className="text-right">Equity</TableHead>
                      <TableHead className="text-right">
                        Total Assets
                      </TableHead>
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
                            {fmtEur(row.equity)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs py-1.5">
                            {fmtEur(row.total_assets)}
                          </TableCell>
                          <TableCell className="text-right font-mono text-xs py-1.5">
                            {fmtNumber(row.fte_total)}
                          </TableCell>
                        </TableRow>
                      ))}
                  </TableBody>
                </Table>
              </div>

              {/* Chart */}
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

              {/* ===== Balance Sheet ===== */}
              <div className="mt-6">
                <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2">
                  Balance Sheet
                </h3>
                <div className="rounded-lg border overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="bg-slate-50">
                        <TableHead className="text-xs min-w-[160px]">Line Item</TableHead>
                        {[...financials.summary]
                          .sort((a, b) => b.fiscal_year - a.fiscal_year)
                          .map((row) => (
                            <TableHead key={row.fiscal_year} className="text-right text-xs min-w-[100px]">
                              FY{row.fiscal_year}
                            </TableHead>
                          ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {/* Assets header */}
                      <TableRow className="bg-slate-50/50">
                        <TableCell className="text-xs font-bold text-slate-700 py-1" colSpan={financials.summary.length + 1}>
                          Assets
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell className="text-xs text-slate-600 py-1">Fixed Assets</TableCell>
                        {[...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year).map((row) => (
                          <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(row.fixed_assets)}</TableCell>
                        ))}
                      </TableRow>
                      <TableRow>
                        <TableCell className="text-xs text-slate-600 py-1">Inventories</TableCell>
                        {[...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year).map((row) => (
                          <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(row.inventories)}</TableCell>
                        ))}
                      </TableRow>
                      <TableRow>
                        <TableCell className="text-xs text-slate-600 py-1">Trade Receivables</TableCell>
                        {[...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year).map((row) => (
                          <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(row.trade_receivables)}</TableCell>
                        ))}
                      </TableRow>
                      <TableRow>
                        <TableCell className="text-xs text-slate-600 py-1">Cash & Investments</TableCell>
                        {[...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year).map((row) => (
                          <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">
                            {fmtEur(((row.cash ?? 0) + (row.current_investments ?? 0)) || null)}
                          </TableCell>
                        ))}
                      </TableRow>
                      <TableRow className="border-t-2 border-slate-300">
                        <TableCell className="text-xs font-bold text-slate-800 py-1">Total Assets</TableCell>
                        {[...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year).map((row) => (
                          <TableCell key={row.fiscal_year} className="text-right font-mono text-xs font-bold py-1">{fmtEur(row.total_assets)}</TableCell>
                        ))}
                      </TableRow>
                      {/* Liabilities & Equity header */}
                      <TableRow className="bg-slate-50/50">
                        <TableCell className="text-xs font-bold text-slate-700 py-1" colSpan={financials.summary.length + 1}>
                          Liabilities & Equity
                        </TableCell>
                      </TableRow>
                      <TableRow>
                        <TableCell className="text-xs text-slate-600 py-1">Equity</TableCell>
                        {[...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year).map((row) => (
                          <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(row.equity)}</TableCell>
                        ))}
                      </TableRow>
                      <TableRow>
                        <TableCell className="text-xs text-slate-600 py-1">LT Financial Debt</TableCell>
                        {[...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year).map((row) => (
                          <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(row.lt_financial_debt)}</TableCell>
                        ))}
                      </TableRow>
                      <TableRow>
                        <TableCell className="text-xs text-slate-600 py-1">ST Financial Debt</TableCell>
                        {[...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year).map((row) => (
                          <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(row.st_financial_debt)}</TableCell>
                        ))}
                      </TableRow>
                      <TableRow>
                        <TableCell className="text-xs text-slate-600 py-1">Trade Payables</TableCell>
                        {[...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year).map((row) => (
                          <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(row.trade_payables)}</TableCell>
                        ))}
                      </TableRow>
                    </TableBody>
                  </Table>
                </div>
              </div>

              {/* ===== Derived Cash Flow ===== */}
              {financials.summary.length >= 2 && (() => {
                const sorted = [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year);
                const cashFlowRows = sorted.slice(0, -1).map((row, idx) => {
                  const prev = sorted[idx + 1];
                  const netDebtCurr = ((row.lt_financial_debt ?? 0) + (row.st_financial_debt ?? 0)) - (row.cash ?? 0);
                  const netDebtPrev = ((prev.lt_financial_debt ?? 0) + (prev.st_financial_debt ?? 0)) - (prev.cash ?? 0);
                  const capex = (row.fixed_assets ?? 0) - (prev.fixed_assets ?? 0) + Math.abs(row.da ?? 0);
                  const wcCurr = (row.inventories ?? 0) + (row.trade_receivables ?? 0) - (row.trade_payables ?? 0);
                  const wcPrev = (prev.inventories ?? 0) + (prev.trade_receivables ?? 0) - (prev.trade_payables ?? 0);
                  const wcChange = wcCurr - wcPrev;
                  return {
                    fiscal_year: row.fiscal_year,
                    ebitda: row.ebitda,
                    wc_change: wcChange !== 0 ? wcChange : null,
                    capex: capex !== 0 ? -Math.abs(capex) : null,
                    net_debt_change: netDebtCurr - netDebtPrev !== 0 ? netDebtCurr - netDebtPrev : null,
                  };
                });
                return (
                  <div className="mt-6">
                    <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-cyan-500 pl-2">
                      Derived Cash Flow
                    </h3>
                    <div className="rounded-lg border overflow-x-auto">
                      <Table>
                        <TableHeader>
                          <TableRow className="bg-slate-50">
                            <TableHead className="text-xs min-w-[160px]">Line Item</TableHead>
                            {cashFlowRows.map((r) => (
                              <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[100px]">
                                FY{r.fiscal_year}
                              </TableHead>
                            ))}
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          <TableRow>
                            <TableCell className="text-xs text-slate-600 py-1">EBITDA</TableCell>
                            {cashFlowRows.map((r) => (
                              <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(r.ebitda)}</TableCell>
                            ))}
                          </TableRow>
                          <TableRow>
                            <TableCell className="text-xs text-slate-600 py-1">Change in Working Capital</TableCell>
                            {cashFlowRows.map((r) => (
                              <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(r.wc_change)}</TableCell>
                            ))}
                          </TableRow>
                          <TableRow>
                            <TableCell className="text-xs text-slate-600 py-1">CapEx (est.)</TableCell>
                            {cashFlowRows.map((r) => (
                              <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(r.capex)}</TableCell>
                            ))}
                          </TableRow>
                          <TableRow className="border-t-2 border-slate-300">
                            <TableCell className="text-xs font-bold text-slate-800 py-1">Net Debt Change</TableCell>
                            {cashFlowRows.map((r) => (
                              <TableCell key={r.fiscal_year} className="text-right font-mono text-xs font-bold py-1">{fmtEur(r.net_debt_change)}</TableCell>
                            ))}
                          </TableRow>
                        </TableBody>
                      </Table>
                    </div>
                    <p className="mt-1 text-[10px] text-slate-400 italic">
                      CapEx estimated as change in fixed assets + D&A. Working capital = inventories + trade receivables - trade payables.
                    </p>
                  </div>
                );
              })()}
            </>
          )}
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
