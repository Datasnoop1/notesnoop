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

      {/* Company header */}
      <div className="mb-4 border-b pb-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold text-slate-900">
                {detail.name || fmtCbe(cbe)}
              </h1>
              {detail.status === "AC" ? (
                <Badge
                  variant="secondary"
                  className="bg-green-50 text-green-700 border-green-200"
                >
                  Active
                </Badge>
              ) : (
                <Badge
                  variant="secondary"
                  className="bg-red-50 text-red-700 border-red-200"
                >
                  Ceased
                </Badge>
              )}
            </div>
            <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-slate-600">
              <span>
                <span className="font-medium text-slate-500">CBE</span>{" "}
                {fmtCbe(cbe)}
              </span>
              {detail.jf_label && (
                <span>
                  <span className="font-medium text-slate-500">Legal form</span>{" "}
                  {detail.jf_label}
                </span>
              )}
              {detail.start_date && (
                <span>
                  <span className="font-medium text-slate-500">Founded</span>{" "}
                  {detail.start_date}
                </span>
              )}
            </div>
            {address && (
              <p className="mt-1 text-sm text-slate-500">{address}</p>
            )}
            {detail.nace_code && (
              <p className="mt-1 text-sm text-slate-500">
                <span className="font-medium">NACE</span> {detail.nace_code}
                {detail.nace_label &&
                  detail.nace_label !== detail.nace_code &&
                  ` - ${detail.nace_label}`}
              </p>
            )}
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleFavourite}
            title={isFavourite ? "Remove from favourites" : "Add to favourites"}
          >
            <Star
              className={`h-5 w-5 ${
                isFavourite
                  ? "fill-yellow-400 text-yellow-500"
                  : "text-slate-300"
              }`}
            />
          </Button>
        </div>
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

        {/* ===== Publications tab ===== */}
        <TabsContent value="publications" className="mt-3">
          {!structure ||
          structure.staatsblad_publications.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              No Staatsblad publications available.
            </p>
          ) : (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow className="bg-slate-50">
                    <TableHead>Date</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Reference</TableHead>
                    <TableHead className="text-right">Link</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {structure.staatsblad_publications.map((pub, i) => (
                    <TableRow key={`${pub.pub_date}-${i}`}>
                      <TableCell className="font-medium text-sm">
                        {pub.pub_date}
                      </TableCell>
                      <TableCell className="text-sm text-slate-600">
                        {pub.pub_type ?? "\u2014"}
                      </TableCell>
                      <TableCell className="text-sm text-slate-500">
                        {pub.reference ?? "\u2014"}
                      </TableCell>
                      <TableCell className="text-right">
                        {pub.pdf_url ? (
                          <a
                            href={
                              pub.pdf_url.startsWith("http")
                                ? pub.pdf_url
                                : `https://www.ejustice.just.fgov.be${pub.pdf_url}`
                            }
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:underline"
                          >
                            PDF <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : (
                          "\u2014"
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
