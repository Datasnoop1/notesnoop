"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import {
  getOutperformersOverview,
  getOutperformersBreakdown,
  type BucketName,
  type OutperformersOverview,
  type OutperformersBreakdown,
  type BucketCompany,
} from "@/lib/api";
import { fmtEur, fmtPct, fmtNumber, fmtCbe } from "@/lib/format";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { TrendingUp, Percent, ArrowUpRight, Users } from "lucide-react";

/* ──────────────────────────────────────────────────────────────
   Bucket metadata (labels + colors)
   ────────────────────────────────────────────────────────────── */

const BUCKET_ORDER: BucketName[] = [
  "revenue_growers",
  "high_margin",
  "margin_growers",
  "other",
];

const BUCKET_META: Record<
  BucketName,
  { label: string; tagline: string; color: string; bg: string; border: string; icon: React.ReactNode }
> = {
  revenue_growers: {
    label: "Revenue growers",
    tagline: "Revenue up \u226510% over the period",
    color: "#6366f1",
    bg: "bg-indigo-50",
    border: "border-indigo-200",
    icon: <TrendingUp className="w-5 h-5" />,
  },
  high_margin: {
    label: "High margin",
    tagline: "EBITDA margin \u226515% in latest year",
    color: "#10b981",
    bg: "bg-emerald-50",
    border: "border-emerald-200",
    icon: <Percent className="w-5 h-5" />,
  },
  margin_growers: {
    label: "Margin growers",
    tagline: "Margin up \u226520% (relative) over the period",
    color: "#f59e0b",
    bg: "bg-amber-50",
    border: "border-amber-200",
    icon: <ArrowUpRight className="w-5 h-5" />,
  },
  other: {
    label: "Other companies",
    tagline: "Companies not in any outperformer bucket",
    color: "#64748b",
    bg: "bg-slate-50",
    border: "border-slate-200",
    icon: <Users className="w-5 h-5" />,
  },
};

/* ──────────────────────────────────────────────────────────────
   Bucket card
   ────────────────────────────────────────────────────────────── */

function BucketCard({
  bucket,
  count,
  medianPct,
  metricLabel,
  totalRevenueM,
  selected,
  onClick,
}: {
  bucket: BucketName;
  count: number;
  medianPct: number | null;
  metricLabel: string;
  totalRevenueM: number;
  selected: boolean;
  onClick: () => void;
}) {
  const meta = BUCKET_META[bucket];
  return (
    <button
      onClick={onClick}
      className={`text-left w-full rounded-lg border-2 transition-all ${
        selected
          ? `${meta.bg} ${meta.border} shadow-md`
          : "bg-white border-slate-200 hover:border-slate-300 hover:shadow-sm"
      }`}
    >
      <CardContent className="p-5">
        <div className="flex items-start justify-between mb-3">
          <div
            className="p-2 rounded-lg text-white"
            style={{ background: meta.color }}
          >
            {meta.icon}
          </div>
          {selected && (
            <span className="text-[11px] uppercase tracking-wider font-semibold text-slate-600 bg-white/70 px-2 py-0.5 rounded">
              Selected
            </span>
          )}
        </div>
        <div className="text-3xl font-extrabold text-slate-900 tracking-tight">
          {fmtNumber(count)}
        </div>
        <div className="text-sm font-semibold text-slate-700 mt-1">{meta.label}</div>
        <div className="text-[11px] text-slate-500 mt-0.5 leading-tight">{meta.tagline}</div>

        <div className="mt-3 pt-3 border-t border-slate-200/60 text-[11px] space-y-0.5">
          {medianPct != null && (
            <div className="text-slate-600">
              <span className="text-slate-400">{metricLabel}: </span>
              <span className="font-semibold">{fmtPct(medianPct)}</span>
            </div>
          )}
          <div className="text-slate-600">
            <span className="text-slate-400">Total revenue: </span>
            <span className="font-semibold">{fmtEur(totalRevenueM * 1e6)}</span>
          </div>
        </div>
      </CardContent>
    </button>
  );
}

/* ──────────────────────────────────────────────────────────────
   Helpers for bucket-specific columns
   ────────────────────────────────────────────────────────────── */

function primaryMetricFor(bucket: BucketName, c: BucketCompany): number | null {
  switch (bucket) {
    case "revenue_growers":
      return c.rev_growth_pct != null ? c.rev_growth_pct * 100 : null;
    case "high_margin":
      return c.margin_25 != null ? c.margin_25 * 100 : null;
    case "margin_growers":
      return c.margin_growth_pct != null ? c.margin_growth_pct * 100 : null;
    case "other":
      return null;
  }
}

function primaryMetricHeader(bucket: BucketName): string {
  switch (bucket) {
    case "revenue_growers":
      return "Rev growth";
    case "high_margin":
      return "Margin 2025";
    case "margin_growers":
      return "Margin growth";
    case "other":
      return "";
  }
}

/* ──────────────────────────────────────────────────────────────
   Page
   ────────────────────────────────────────────────────────────── */

export default function OutperformersPage() {
  const [overview, setOverview] = useState<OutperformersOverview | null>(null);
  const [selected, setSelected] = useState<BucketName>("revenue_growers");
  const [breakdown, setBreakdown] = useState<OutperformersBreakdown | null>(null);
  const [loadingOverview, setLoadingOverview] = useState(true);
  const [loadingBreakdown, setLoadingBreakdown] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 640);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  useEffect(() => {
    setLoadingOverview(true);
    getOutperformersOverview()
      .then((r) => setOverview(r))
      .catch((e) => setErr(String(e)))
      .finally(() => setLoadingOverview(false));
  }, []);

  useEffect(() => {
    setLoadingBreakdown(true);
    setBreakdown(null);
    getOutperformersBreakdown(selected, 15, 25)
      .then((r) => setBreakdown(r))
      .catch((e) => setErr(String(e)))
      .finally(() => setLoadingBreakdown(false));
  }, [selected]);

  const meta = BUCKET_META[selected];
  const baseYear = overview?.base_year ?? 2023;
  const endYear = overview?.end_year ?? 2025;

  return (
    <div className="mx-auto w-full max-w-[1200px] space-y-8 pb-16">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center text-[11px] uppercase tracking-wider font-semibold text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded">
            Experimental
          </span>
        </div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight mt-2">
          Outperformers
        </h1>
        <p className="mt-2 text-sm text-slate-500 max-w-3xl">
          Which Belgian companies are outperforming? Companies are sorted into
          three overlapping outperformer buckets (plus a catch-all "other"
          bucket). Click a bucket to see its sector mix and top companies.
        </p>
        {overview && (
          <p className="mt-2 text-xs text-slate-400">
            Universe: {fmtNumber(overview.universe)} companies with revenue in both {baseYear} and {endYear} and {baseYear} revenue &ge; {fmtEur(overview.thresholds.min_revenue)}.
            A company can appear in multiple outperformer buckets.
          </p>
        )}
      </div>

      {err && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          Failed to load: {err}
        </div>
      )}

      {/* Bucket cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {BUCKET_ORDER.map((b) => {
          const bucketData = overview?.buckets[b];
          return (
            <BucketCard
              key={b}
              bucket={b}
              count={bucketData?.count ?? 0}
              medianPct={bucketData?.median_metric_pct ?? null}
              metricLabel={bucketData?.metric_label ?? ""}
              totalRevenueM={bucketData?.total_revenue_m ?? 0}
              selected={selected === b}
              onClick={() => setSelected(b)}
            />
          );
        })}
      </div>

      {loadingOverview && (
        <p className="text-xs text-slate-400">Loading bucket counts&hellip;</p>
      )}

      {/* Drill-down */}
      <div className="space-y-6">
        <div>
          <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <span className="inline-block w-3 h-3 rounded-full" style={{ background: meta.color }} />
            {meta.label} — sector mix
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Top 15 activities (2-digit NACE) among companies in this bucket.
          </p>
        </div>

        <Card className="bg-white p-4">
          {loadingBreakdown ? (
            <div className="h-80 animate-pulse rounded bg-slate-100" />
          ) : !breakdown || breakdown.sectors.length === 0 ? (
            <div className="h-40 flex items-center justify-center text-slate-400 text-sm">
              No sector data for this bucket.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(320, breakdown.sectors.length * 30)}>
              <BarChart
                data={[...breakdown.sectors].reverse()}
                layout="vertical"
                margin={{ top: 5, right: isMobile ? 12 : 40, left: isMobile ? 0 : 10, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} axisLine={{ stroke: "#cbd5e1" }} />
                <YAxis
                  type="category"
                  dataKey="sector"
                  width={isMobile ? 120 : 240}
                  tick={{ fontSize: 11, fill: "#475569" }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v: string) => {
                    const limit = isMobile ? 16 : 34;
                    return v.length > limit ? v.slice(0, limit - 2) + "\u2026" : v;
                  }}
                />
                <Tooltip
                  content={({ active, payload }: any) => {
                    if (!active || !payload?.[0]) return null;
                    const d = payload[0].payload;
                    return (
                      <div className="rounded border border-slate-200 bg-white px-3 py-2 shadow-lg text-sm">
                        <div className="font-semibold text-slate-800 mb-1">
                          {d.nace2} — {d.sector}
                        </div>
                        <div className="text-slate-600">Companies: <span className="font-semibold">{fmtNumber(d.companies)}</span></div>
                        <div className="text-slate-600">Revenue: <span className="font-semibold">{fmtEur(d.revenue_m * 1e6)}</span></div>
                        <div className="text-slate-600">EBITDA: <span className="font-semibold">{fmtEur(d.ebitda_m * 1e6)}</span></div>
                      </div>
                    );
                  }}
                  cursor={{ fill: "rgba(99,102,241,0.06)" }}
                />
                <Bar dataKey="companies" radius={[0, 4, 4, 0]}>
                  {breakdown.sectors.map((_, idx) => (
                    <Cell key={idx} fill={meta.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>

        {/* Top companies */}
        <div>
          <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
            <span className="inline-block w-3 h-3 rounded-full" style={{ background: meta.color }} />
            {meta.label} — top companies
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Top 25 by {selected === "revenue_growers"
              ? "revenue growth"
              : selected === "high_margin"
              ? "EBITDA margin"
              : selected === "margin_growers"
              ? "margin growth"
              : "revenue"}.
          </p>
        </div>

        <Card className="bg-white overflow-hidden">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-slate-50/80">
                  <TableHead className="text-[11px] uppercase tracking-wider">Company</TableHead>
                  <TableHead className="text-[11px] uppercase tracking-wider">Sector</TableHead>
                  <TableHead className="text-[11px] uppercase tracking-wider">City</TableHead>
                  <TableHead className="text-right text-[11px] uppercase tracking-wider">Revenue {endYear}</TableHead>
                  <TableHead className="text-right text-[11px] uppercase tracking-wider">EBITDA {endYear}</TableHead>
                  {selected !== "other" && (
                    <TableHead className="text-right text-[11px] uppercase tracking-wider">
                      {primaryMetricHeader(selected)}
                    </TableHead>
                  )}
                </TableRow>
              </TableHeader>
              <TableBody>
                {loadingBreakdown ? (
                  Array.from({ length: 10 }).map((_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: selected === "other" ? 5 : 6 }).map((_, j) => (
                        <TableCell key={j}>
                          <div className="h-4 w-full animate-pulse rounded bg-slate-100" />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : !breakdown || breakdown.companies.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={selected === "other" ? 5 : 6} className="text-center py-10 text-slate-400">
                      No companies in this bucket.
                    </TableCell>
                  </TableRow>
                ) : (
                  breakdown.companies.map((c) => {
                    const metric = primaryMetricFor(selected, c);
                    return (
                      <TableRow key={c.cbe} className="hover:bg-indigo-50/30 text-[13px]">
                        <TableCell className="py-2">
                          <Link
                            href={`/company/${c.cbe}`}
                            className="text-indigo-600 hover:text-indigo-800 hover:underline font-medium"
                          >
                            {c.name || fmtCbe(c.cbe)}
                          </Link>
                          <div className="text-[11px] text-slate-400 font-mono">{fmtCbe(c.cbe)}</div>
                        </TableCell>
                        <TableCell className="py-2 max-w-[140px] sm:max-w-[240px] truncate" title={c.sector ?? ""}>
                          {c.sector ?? <span className="text-slate-400 italic">—</span>}
                        </TableCell>
                        <TableCell className="py-2 text-slate-600">{c.city ?? "—"}</TableCell>
                        <TableCell className="text-right font-mono text-[12px] py-2">
                          {fmtEur(c.rev_25)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-[12px] py-2">
                          {fmtEur(c.ebitda_25)}
                        </TableCell>
                        {selected !== "other" && (
                          <TableCell className="text-right font-mono text-[12px] py-2">
                            <span
                              className="font-semibold"
                              style={{ color: metric != null && metric > 0 ? meta.color : "#94a3b8" }}
                            >
                              {fmtPct(metric)}
                            </span>
                          </TableCell>
                        )}
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </Card>
      </div>

      {/* Methodology footer */}
      <div className="text-[11px] text-slate-400 border-t border-slate-200 pt-4 leading-relaxed">
        <p className="font-semibold text-slate-500 mb-1">Methodology</p>
        <ul className="list-disc list-inside space-y-0.5">
          <li>Universe: companies with revenue in both {baseYear} and {endYear} and {baseYear} revenue &ge; €1M.</li>
          <li>Revenue growers: total revenue growth {baseYear}-{endYear} &ge; 10%.</li>
          <li>High margin: EBITDA margin in {endYear} &ge; 15%.</li>
          <li>Margin growers: EBITDA margin grew by &ge; 20% relative (base margin &ge; 2% to avoid near-zero divisions).</li>
          <li>Buckets overlap — a company can qualify for several. "Other" is exclusive.</li>
        </ul>
      </div>
    </div>
  );
}
