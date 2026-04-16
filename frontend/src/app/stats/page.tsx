"use client";

import { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import ExportButtons from "@/components/export-buttons";
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
  getStatsOverview,
  getStatsSectors,
  getStatsMarginDistribution,
  getStatsSizeDistribution,
  getStatsEvolution,
  getStatsProvinces,
  type StatsOverview,
  type StatsSector,
  type MarginBucket,
  type SizeBucket,
  type EvolutionYear,
  type ProvinceStats,
} from "@/lib/api";
import { fmtEur, fmtPct, fmtNumber } from "@/lib/format";
import { useTranslation } from "@/components/language-provider";
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  BarChart3,
  Building2,
  DollarSign,
  TrendingUp,
  Percent,
  Users,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  LineChart,
  Line,
  Legend,
} from "recharts";

/* ============================================================
   Helpers
   ============================================================ */

function SkeletonBlock({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-slate-200 ${className}`} />;
}

function SkeletonRows({ cols, count }: { cols: number; count: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <TableRow key={i}>
          {Array.from({ length: cols }).map((_, j) => (
            <TableCell key={j}>
              <SkeletonBlock className="h-4 w-full" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

function SectionHeader({ children, icon }: { children: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 border-l-2 border-indigo-600 pl-2 mb-4 flex items-center gap-1.5">
      {icon}{children}
    </h2>
  );
}

function ChartSkeleton({ height = "h-80" }: { height?: string }) {
  return (
    <div className={`${height} animate-pulse rounded-lg bg-slate-100 flex items-center justify-center`}>
      <BarChart3 className="h-10 w-10 text-slate-300" />
    </div>
  );
}

/* margin -> color (green for high, red for low/negative) */
function marginColor(margin: number | null | undefined): string {
  if (margin == null) return "#94a3b8"; // slate-400
  if (margin >= 20) return "#059669";   // emerald-600
  if (margin >= 12) return "#10b981";   // emerald-500
  if (margin >= 6) return "#f59e0b";    // amber-500
  if (margin >= 0) return "#f97316";    // orange-500
  return "#ef4444";                     // red-500
}

/* lighter version for backgrounds */
function marginBg(margin: number | null | undefined): string {
  if (margin == null) return "bg-slate-50";
  if (margin >= 20) return "bg-emerald-50";
  if (margin >= 12) return "bg-emerald-50";
  if (margin >= 6) return "bg-amber-50";
  if (margin >= 0) return "bg-orange-50";
  return "bg-red-50";
}

function marginTextColor(margin: number | null | undefined): string {
  if (margin == null) return "text-slate-400";
  if (margin >= 20) return "text-emerald-700";
  if (margin >= 12) return "text-emerald-600";
  if (margin >= 6) return "text-amber-700";
  if (margin >= 0) return "text-orange-600";
  return "text-red-600";
}

/* Size bucket color palette */
const SIZE_COLORS = [
  "#6366f1", "#818cf8", "#a5b4fc", "#c7d2fe",
  "#7c3aed", "#8b5cf6", "#a78bfa", "#c4b5fd",
];

/* Province palette */
const PROVINCE_COLORS = [
  "#6366f1", "#8b5cf6", "#ec4899", "#f43f5e",
  "#f97316", "#eab308", "#22c55e", "#14b8a6",
  "#06b6d4", "#3b82f6", "#a855f7",
];

/* ============================================================
   Sorting (for the table)
   ============================================================ */

type SortKey = "nace2" | "sector" | "companies" | "revenue_m" | "ebitda_m" | "med_margin" | "med_fte";
type SortDir = "asc" | "desc";

function sortSectors(data: StatsSector[], key: SortKey, dir: SortDir): StatsSector[] {
  return [...data].sort((a, b) => {
    const av = a[key as keyof StatsSector];
    const bv = b[key as keyof StatsSector];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    const cmp = typeof av === "string" ? av.localeCompare(bv as string) : (av as number) - (bv as number);
    return dir === "asc" ? cmp : -cmp;
  });
}

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return <ArrowUpDown className="ml-1 inline h-3 w-3 text-slate-300" />;
  return dir === "asc"
    ? <ArrowUp className="ml-1 inline h-3 w-3 text-indigo-600" />
    : <ArrowDown className="ml-1 inline h-3 w-3 text-indigo-600" />;
}

/* ============================================================
   Custom Recharts tooltips
   ============================================================ */

function SectorBarTooltip({ active, payload }: any) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  const naceLabel = d.sector && d.sector !== d.nace2
    ? `${d.nace2} \u2014 ${d.sector}`
    : d.nace2;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-lg text-sm">
      <p className="font-semibold text-slate-800 mb-1">{naceLabel}</p>
      <p className="text-slate-600">Companies: <span className="font-semibold">{fmtNumber(d.companies)}</span></p>
      <p className="text-slate-600">Revenue: <span className="font-semibold">{fmtEur(d.revenue_m * 1e6)}</span></p>
      <p className="text-slate-600">EBITDA: <span className="font-semibold">{fmtEur(d.ebitda_m * 1e6)}</span></p>
      <p className="text-slate-600">Median Margin: <span className="font-semibold" style={{ color: marginColor(d.med_margin) }}>{fmtPct(d.med_margin)}</span></p>
      <p className="text-slate-600">Median FTE: <span className="font-semibold">{fmtNumber(d.med_fte)}</span></p>
    </div>
  );
}

function SizeTooltip({ active, payload }: any) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-lg text-sm">
      <p className="font-semibold text-slate-800 mb-1">{d.size_bucket}</p>
      <p className="text-slate-600">Companies: <span className="font-semibold">{fmtNumber(d.companies)}</span></p>
      <p className="text-slate-600">Total Revenue: <span className="font-semibold">{fmtEur(d.revenue_m * 1e6)}</span></p>
    </div>
  );
}

function MarginTooltip({ active, payload }: any) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-lg text-sm">
      <p className="font-semibold text-slate-800 mb-1">Margin: {d.margin_bucket}%</p>
      <p className="text-slate-600">Companies: <span className="font-semibold">{fmtNumber(d.n)}</span></p>
    </div>
  );
}

function EvolutionTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-lg text-sm">
      <p className="font-semibold text-slate-800 mb-1">Fiscal Year {label}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} className="text-slate-600" style={{ color: p.color }}>
          {p.name}: <span className="font-semibold">{typeof p.value === "number" ? `${p.value.toFixed(1)}M` : p.value}</span>
        </p>
      ))}
    </div>
  );
}

function ProvinceTooltip({ active, payload }: any) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-lg text-sm">
      <p className="font-semibold text-slate-800 mb-1">{d.province}</p>
      <p className="text-slate-600">Companies: <span className="font-semibold">{fmtNumber(d.companies)}</span></p>
      <p className="text-slate-600">Revenue: <span className="font-semibold">{fmtEur(d.revenue_m * 1e6)}</span></p>
      <p className="text-slate-600">EBITDA: <span className="font-semibold">{fmtEur(d.ebitda_m * 1e6)}</span></p>
      <p className="text-slate-600">Median Margin: <span className="font-semibold">{fmtPct(d.med_margin)}</span></p>
      <p className="text-slate-600">Total FTE: <span className="font-semibold">{fmtNumber(d.total_fte)}</span></p>
    </div>
  );
}

/* ============================================================
   KPI Card
   ============================================================ */

interface KpiCardProps {
  label: string;
  value: string;
  icon: React.ReactNode;
  color: string;
  loading: boolean;
}

function KpiCard({ label, value, icon, color, loading }: KpiCardProps) {
  return (
    <Card className={`${color} border-0 shadow-sm hover:shadow-md transition-shadow`}>
      <CardContent className="pt-5 pb-4 px-5">
        {loading ? (
          <>
            <SkeletonBlock className="h-10 w-28 mb-2" />
            <SkeletonBlock className="h-3 w-20" />
          </>
        ) : (
          <div className="flex items-start justify-between">
            <div>
              <div className="text-xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
                {value}
              </div>
              <div className="text-[11px] uppercase tracking-widest text-slate-500 mt-1.5 font-medium">
                {label}
              </div>
            </div>
            <div className="p-2 rounded-lg bg-white/60 text-slate-600">
              {icon}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ============================================================
   Main Page
   ============================================================ */

export default function StatsPage() {
  const { t } = useTranslation();
  /* ---------- responsive ---------- */
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 640);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  /* ---------- state ---------- */
  const [overview, setOverview] = useState<StatsOverview | null>(null);
  const [sectors, setSectors] = useState<StatsSector[]>([]);
  const [marginDist, setMarginDist] = useState<MarginBucket[]>([]);
  const [sizeDist, setSizeDist] = useState<SizeBucket[]>([]);
  const [evolution, setEvolution] = useState<EvolutionYear[]>([]);
  const [provinces, setProvinces] = useState<ProvinceStats[]>([]);

  const [loading, setLoading] = useState(true);
  const [chartsLoading, setChartsLoading] = useState(true);

  const [sortKey, setSortKey] = useState<SortKey>("companies");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  /* ---------- fetch data ---------- */
  useEffect(() => {
    // Primary data (KPI + sectors)
    Promise.all([getStatsOverview(), getStatsSectors(undefined, 50)])
      .then(([ov, sec]) => {
        setOverview(ov);
        setSectors(sec);
      })
      .catch(console.error)
      .finally(() => setLoading(false));

    // Chart data (can load slightly after)
    Promise.all([
      getStatsMarginDistribution(),
      getStatsSizeDistribution(),
      getStatsEvolution(2019, 2024),
      getStatsProvinces(),
    ])
      .then(([md, sd, ev, pv]) => {
        setMarginDist(md);
        setSizeDist(sd);
        setEvolution(ev);
        setProvinces(pv);
      })
      .catch(console.error)
      .finally(() => setChartsLoading(false));
  }, []);

  /* ---------- derived data ---------- */
  const sorted = useMemo(
    () => sortSectors(sectors, sortKey, sortDir),
    [sectors, sortKey, sortDir],
  );

  // Top 20 sectors for the bar chart
  const sectorBarData = useMemo(() => {
    const top = [...sectors]
      .sort((a, b) => b.companies - a.companies)
      .slice(0, 20)
      .reverse() // reverse so largest is at top of horizontal bar
      .map((s) => ({
        ...s,
        naceDisplay: s.sector && s.sector !== s.nace2
          ? `${s.nace2} \u2014 ${s.sector}`
          : s.nace2,
      }));
    return top;
  }, [sectors]);

  // Revenue per sector for the second bar chart (avg revenue)
  const revenuePerSector = useMemo(() => {
    return [...sectors]
      .filter((s) => s.companies > 0 && s.revenue_m > 0)
      .map((s) => {
        const fullLabel = s.sector && s.sector !== s.nace2
          ? `${s.nace2} \u2014 ${s.sector}`
          : s.nace2;
        return {
          ...s,
          avg_revenue_k: Math.round((s.revenue_m * 1000) / s.companies),
          label: fullLabel.length > 36 ? fullLabel.slice(0, 34) + "..." : fullLabel,
        };
      })
      .sort((a, b) => b.avg_revenue_k - a.avg_revenue_k)
      .slice(0, 15)
      .reverse();
  }, [sectors]);

  // Margin distribution: group into wider buckets for cleaner histogram
  const marginHistData = useMemo(() => {
    if (!marginDist.length) return [];
    // Group into 5% buckets
    const buckets = new Map<number, number>();
    for (const row of marginDist) {
      const bucket = Math.floor(row.margin_bucket / 5) * 5;
      buckets.set(bucket, (buckets.get(bucket) || 0) + row.n);
    }
    return Array.from(buckets.entries())
      .map(([bucket, n]) => ({ margin_bucket: bucket, n, label: `${bucket}% - ${bucket + 5}%` }))
      .sort((a, b) => a.margin_bucket - b.margin_bucket);
  }, [marginDist]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  const colHeaders: { key: SortKey; label: string; align?: string }[] = [
    { key: "nace2", label: t("stats.nace") },
    { key: "sector", label: t("stats.sector") },
    { key: "companies", label: t("stats.companies"), align: "text-right" },
    { key: "revenue_m", label: `${t("stats.revenue")} (M)`, align: "text-right" },
    { key: "ebitda_m", label: `${t("stats.ebitda")} (M)`, align: "text-right" },
    { key: "med_margin", label: t("stats.medianMargin"), align: "text-right" },
    { key: "med_fte", label: t("stats.medianFte"), align: "text-right" },
  ];

  return (
    <div className="space-y-10 pb-16">

      {/* ━━━━━━━━━━ HEADER ━━━━━━━━━━ */}
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
          <BarChart3 className="w-6 h-6 sm:w-7 sm:h-7 inline mr-2 -mt-1 text-indigo-600" />
          {t("stats.title")}
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Aggregate financial data across all sectors and provinces in the Belgian company database
        </p>
      </div>

      {/* ━━━━━━━━━━ SECTION 1: KPI CARDS ━━━━━━━━━━ */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <KpiCard
          label={t("stats.companies")}
          value={overview ? fmtNumber(overview.n_companies) : "--"}
          icon={<Building2 className="w-5 h-5" />}
          color="bg-blue-50"
          loading={loading}
        />
        <KpiCard
          label={t("stats.totalRevenue")}
          value={overview ? fmtEur(overview.total_revenue) : "--"}
          icon={<DollarSign className="w-5 h-5" />}
          color="bg-emerald-50"
          loading={loading}
        />
        <KpiCard
          label={t("stats.totalEbitda")}
          value={overview ? fmtEur(overview.total_ebitda) : "--"}
          icon={<TrendingUp className="w-5 h-5" />}
          color="bg-violet-50"
          loading={loading}
        />
        <KpiCard
          label={t("stats.medianMargin")}
          value={overview ? fmtPct(overview.median_margin) : "--"}
          icon={<Percent className="w-5 h-5" />}
          color="bg-amber-50"
          loading={loading}
        />
        <KpiCard
          label={t("stats.totalFte")}
          value={overview ? fmtNumber(overview.total_fte) : "--"}
          icon={<Users className="w-5 h-5" />}
          color="bg-rose-50"
          loading={loading}
        />
      </div>

      {/* ━━━━━━━━━━ SECTION 2: SECTOR BAR CHART ━━━━━━━━━━ */}
      <div>
        <SectionHeader>Sector Breakdown -- Top 20 by Company Count</SectionHeader>
        <Card className="bg-white p-3 sm:p-6">
          {loading ? (
            <ChartSkeleton height="h-[600px]" />
          ) : sectorBarData.length === 0 ? (
            <div className="h-80 flex items-center justify-center text-slate-400">No sector data</div>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(400, sectorBarData.length * 32)}>
              <BarChart
                data={sectorBarData}
                layout="vertical"
                margin={{ top: 5, right: isMobile ? 15 : 40, left: isMobile ? 0 : 10, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                <XAxis
                  type="number"
                  tick={{ fontSize: 11, fill: "#64748b" }}
                  axisLine={{ stroke: "#cbd5e1" }}
                />
                <YAxis
                  type="category"
                  dataKey="naceDisplay"
                  width={isMobile ? 120 : 260}
                  tick={{ fontSize: isMobile ? 10 : 11, fill: "#475569" }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v: string) => {
                    const max = isMobile ? 16 : 38;
                    return v.length > max ? v.slice(0, max - 2) + "..." : v;
                  }}
                />
                <Tooltip content={<SectorBarTooltip />} cursor={{ fill: "rgba(99,102,241,0.06)" }} />
                <Bar
                  dataKey="companies"
                  radius={[0, 4, 4, 0]}
                  cursor="pointer"
                  onClick={(data: any) => {
                    if (data?.nace2) {
                      window.location.href = `/screener?nace=${data.nace2}`;
                    }
                  }}
                >
                  {sectorBarData.map((entry, idx) => (
                    <Cell key={idx} fill={marginColor(entry.med_margin)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-slate-400 px-2">
            <span>Bar color = median EBITDA margin:</span>
            <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{ background: "#059669" }} /> &ge;20%</span>
            <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{ background: "#10b981" }} /> 12-20%</span>
            <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{ background: "#f59e0b" }} /> 6-12%</span>
            <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{ background: "#f97316" }} /> 0-6%</span>
            <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{ background: "#ef4444" }} /> &lt;0%</span>
            <span className="sm:ml-auto">Click a bar to filter the screener</span>
          </div>
        </Card>
      </div>

      {/* ━━━━━━━━━━ SECTION 3: TWO-COLUMN CHARTS ━━━━━━━━━━ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Revenue Distribution (size buckets) */}
        <div>
          <SectionHeader>Company Size Distribution</SectionHeader>
          <Card className="bg-white p-3 sm:p-6">
            {chartsLoading ? (
              <ChartSkeleton />
            ) : sizeDist.length === 0 ? (
              <div className="h-80 flex items-center justify-center text-slate-400">No data</div>
            ) : (
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={sizeDist} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                  <XAxis
                    dataKey="size_bucket"
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    axisLine={{ stroke: "#cbd5e1" }}
                    angle={-30}
                    textAnchor="end"
                    height={50}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip content={<SizeTooltip />} cursor={{ fill: "rgba(99,102,241,0.06)" }} />
                  <Bar dataKey="companies" radius={[4, 4, 0, 0]}>
                    {sizeDist.map((_, idx) => (
                      <Cell key={idx} fill={SIZE_COLORS[idx % SIZE_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
            <p className="text-[10px] text-slate-400 mt-2 px-1">Number of companies in each revenue bracket</p>
          </Card>
        </div>

        {/* Margin Distribution */}
        <div>
          <SectionHeader>EBITDA Margin Distribution</SectionHeader>
          <Card className="bg-white p-3 sm:p-6">
            {chartsLoading ? (
              <ChartSkeleton />
            ) : marginHistData.length === 0 ? (
              <div className="h-80 flex items-center justify-center text-slate-400">No data</div>
            ) : (
              <ResponsiveContainer width="100%" height={320}>
                <BarChart data={marginHistData} margin={{ top: 10, right: 20, left: 0, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                  <XAxis
                    dataKey="margin_bucket"
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    axisLine={{ stroke: "#cbd5e1" }}
                    tickFormatter={(v: number) => `${v}%`}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip content={<MarginTooltip />} cursor={{ fill: "rgba(99,102,241,0.06)" }} />
                  <Bar dataKey="n" radius={[4, 4, 0, 0]}>
                    {marginHistData.map((entry, idx) => (
                      <Cell key={idx} fill={marginColor(entry.margin_bucket + 2.5)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
            <p className="text-[10px] text-slate-400 mt-2 px-1">Distribution of EBITDA margins (5% buckets, companies with revenue &gt; 100K)</p>
          </Card>
        </div>
      </div>

      {/* ━━━━━━━━━━ SECTION 4: EVOLUTION LINE CHART ━━━━━━━━━━ */}
      <div>
        <SectionHeader>Financial Evolution (2019-2024)</SectionHeader>
        <Card className="bg-white p-3 sm:p-6">
          {chartsLoading ? (
            <ChartSkeleton />
          ) : evolution.length === 0 ? (
            <div className="h-80 flex items-center justify-center text-slate-400">No evolution data</div>
          ) : (
            <ResponsiveContainer width="100%" height={380}>
              <LineChart data={evolution} margin={{ top: 10, right: 30, left: 10, bottom: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis
                  dataKey="fiscal_year"
                  tick={{ fontSize: 12, fill: "#475569" }}
                  axisLine={{ stroke: "#cbd5e1" }}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "#64748b" }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v: number) => `${v}M`}
                />
                <Tooltip content={<EvolutionTooltip />} />
                <Legend
                  iconType="circle"
                  wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                />
                <Line
                  type="monotone"
                  dataKey="revenue_m"
                  name={t("stats.revenue")}
                  stroke="#6366f1"
                  strokeWidth={2.5}
                  dot={{ r: 4, fill: "#6366f1" }}
                  activeDot={{ r: 6 }}
                />
                <Line
                  type="monotone"
                  dataKey="ebitda_m"
                  name={t("stats.ebitda")}
                  stroke="#10b981"
                  strokeWidth={2.5}
                  dot={{ r: 4, fill: "#10b981" }}
                  activeDot={{ r: 6 }}
                />
                <Line
                  type="monotone"
                  dataKey="net_profit_m"
                  name={t("stats.netProfit")}
                  stroke="#f59e0b"
                  strokeWidth={2}
                  dot={{ r: 3, fill: "#f59e0b" }}
                  strokeDasharray="5 3"
                />
              </LineChart>
            </ResponsiveContainer>
          )}
          <p className="text-[10px] text-slate-400 mt-2 px-1">All figures in millions EUR (aggregate of all companies in database)</p>
        </Card>
      </div>

      {/* ━━━━━━━━━━ SECTION 5: TWO COLUMN - PROVINCES + AVG REVENUE ━━━━━━━━━━ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Province breakdown */}
        <div>
          <SectionHeader>Companies by Province</SectionHeader>
          <Card className="bg-white p-3 sm:p-6">
            {chartsLoading ? (
              <ChartSkeleton height="h-96" />
            ) : provinces.length === 0 ? (
              <div className="h-80 flex items-center justify-center text-slate-400">No data</div>
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(320, provinces.length * 34)}>
                <BarChart
                  data={[...provinces].sort((a, b) => a.companies - b.companies)}
                  layout="vertical"
                  margin={{ top: 5, right: isMobile ? 15 : 40, left: isMobile ? 0 : 10, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    axisLine={{ stroke: "#cbd5e1" }}
                  />
                  <YAxis
                    type="category"
                    dataKey="province"
                    width={isMobile ? 90 : 130}
                    tick={{ fontSize: isMobile ? 10 : 11, fill: "#475569" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip content={<ProvinceTooltip />} cursor={{ fill: "rgba(99,102,241,0.06)" }} />
                  <Bar dataKey="companies" radius={[0, 4, 4, 0]}>
                    {[...provinces]
                      .sort((a, b) => a.companies - b.companies)
                      .map((_, idx) => (
                        <Cell key={idx} fill={PROVINCE_COLORS[idx % PROVINCE_COLORS.length]} />
                      ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>
        </div>

        {/* Average Revenue by Sector */}
        <div>
          <SectionHeader>Average Revenue per Company by Sector</SectionHeader>
          <Card className="bg-white p-3 sm:p-6">
            {loading ? (
              <ChartSkeleton height="h-96" />
            ) : revenuePerSector.length === 0 ? (
              <div className="h-80 flex items-center justify-center text-slate-400">No data</div>
            ) : (
              <ResponsiveContainer width="100%" height={Math.max(320, revenuePerSector.length * 34)}>
                <BarChart
                  data={revenuePerSector}
                  layout="vertical"
                  margin={{ top: 5, right: isMobile ? 15 : 40, left: isMobile ? 0 : 10, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    axisLine={{ stroke: "#cbd5e1" }}
                    tickFormatter={(v: number) => `${v}K`}
                  />
                  <YAxis
                    type="category"
                    dataKey="label"
                    width={isMobile ? 100 : 220}
                    tick={{ fontSize: isMobile ? 10 : 11, fill: "#475569" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    cursor={{ fill: "rgba(99,102,241,0.06)" }}
                    formatter={(value) => [`EUR ${fmtNumber(value as number)}K`, t("stats.avgRevenue")]}
                    labelFormatter={(label) => String(label)}
                    contentStyle={{ borderRadius: 8, border: "1px solid #e2e8f0", fontSize: 12 }}
                  />
                  <Bar dataKey="avg_revenue_k" radius={[0, 4, 4, 0]}>
                    {revenuePerSector.map((entry, idx) => (
                      <Cell key={idx} fill={marginColor(entry.med_margin)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
            <p className="text-[10px] text-slate-400 mt-2 px-1">Top 15 sectors by average revenue per company (in thousands EUR)</p>
          </Card>
        </div>
      </div>

      {/* ━━━━━━━━━━ SECTION 6: FULL SORTABLE SECTOR TABLE ━━━━━━━━━━ */}
      <div>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <SectionHeader>All Sectors -- Detailed Breakdown</SectionHeader>
          <ExportButtons
            onExportCSV={() => {
              const headers = ["NACE", "Sector", "Companies", "Revenue (M)", "EBITDA (M)", "Median Margin", "Median FTE"];
              const csvLines = sorted.map(row => [
                row.nace2,
                `"${(row.sector || "").replace(/"/g, '""')}"`,
                row.companies,
                row.revenue_m != null ? row.revenue_m.toFixed(2) : "",
                row.ebitda_m != null ? row.ebitda_m.toFixed(2) : "",
                row.med_margin != null ? row.med_margin.toFixed(1) : "",
                row.med_fte != null ? String(row.med_fte) : "",
              ].join(","));
              const blob = new Blob([headers.join(",") + "\n" + csvLines.join("\n")], { type: "text/csv" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = "sector_stats.csv";
              a.click();
              URL.revokeObjectURL(url);
            }}
            onPrint={() => window.print()}
          />
        </div>
        <Card className="bg-white overflow-hidden">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50/80">
                  {colHeaders.map((col) => (
                    <TableHead
                      key={col.key}
                      className={`cursor-pointer select-none whitespace-nowrap text-[11px] uppercase tracking-wider ${col.align ?? ""}`}
                      onClick={() => toggleSort(col.key)}
                    >
                      {col.label}
                      <SortIcon active={sortKey === col.key} dir={sortDir} />
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading ? (
                  <SkeletonRows cols={7} count={10} />
                ) : sorted.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center py-12 text-slate-400">
                      No sector data available
                    </TableCell>
                  </TableRow>
                ) : (
                  sorted.map((row) => {
                    const sectorDisplay = row.sector && row.sector !== row.nace2
                      ? `${row.nace2} \u2014 ${row.sector}`
                      : row.nace2;
                    return (
                    <TableRow key={row.nace2} className="hover:bg-indigo-50/30 text-[13px]">
                      <TableCell className="font-medium py-2">
                        <Link
                          href={`/screener?nace=${row.nace2}`}
                          className="text-indigo-600 hover:text-indigo-800 hover:underline font-mono"
                        >
                          {row.nace2}
                        </Link>
                      </TableCell>
                      <TableCell className="max-w-[280px] truncate py-2" title={sectorDisplay}>
                        {row.sector && row.sector !== row.nace2 ? (
                          <Link
                            href={`/screener?nace=${row.nace2}`}
                            className="text-indigo-600 hover:text-indigo-800 hover:underline"
                          >
                            {row.sector}
                          </Link>
                        ) : (
                          <span className="text-slate-400 italic">No description</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono text-[12px] py-2">
                        {fmtNumber(row.companies)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-[12px] py-2">
                        {fmtEur(row.revenue_m != null ? row.revenue_m * 1e6 : null)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-[12px] py-2">
                        {fmtEur(row.ebitda_m != null ? row.ebitda_m * 1e6 : null)}
                      </TableCell>
                      <TableCell className="text-right py-2">
                        <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold ${marginBg(row.med_margin)} ${marginTextColor(row.med_margin)}`}>
                          {fmtPct(row.med_margin)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right font-mono text-[12px] py-2">
                        {fmtNumber(row.med_fte)}
                      </TableCell>
                    </TableRow>
                  );})
                )}
              </TableBody>
            </Table>
          </div>
        </Card>
      </div>

    </div>
  );
}
