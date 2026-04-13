"use client";

import { useEffect, useState, useMemo } from "react";
import Link from "next/link";
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
  type StatsOverview,
  type StatsSector,
} from "@/lib/api";
import { fmtEur, fmtPct, fmtNumber } from "@/lib/format";
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";

/* ---------- skeleton helpers ---------- */

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

/* ---------- KPI card meta ---------- */

interface KpiMeta {
  label: string;
  fmt: (v: number | null | undefined) => string;
  key: keyof StatsOverview;
}

const KPI_META: KpiMeta[] = [
  { key: "n_companies", label: "Total Companies", fmt: (v) => fmtNumber(v) },
  { key: "total_revenue", label: "Total Revenue", fmt: (v) => fmtEur(v) },
  { key: "total_ebitda", label: "Total EBITDA", fmt: (v) => fmtEur(v) },
  { key: "median_margin", label: "Median Margin", fmt: (v) => fmtPct(v) },
  { key: "total_fte", label: "Total FTE", fmt: (v) => fmtNumber(v) },
];

/* ---------- sorting ---------- */

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

/* ---------- main component ---------- */

export default function StatsPage() {
  const [overview, setOverview] = useState<StatsOverview | null>(null);
  const [sectors, setSectors] = useState<StatsSector[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("companies");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  useEffect(() => {
    Promise.all([getStatsOverview(), getStatsSectors(undefined, 25)])
      .then(([ov, sec]) => {
        setOverview(ov);
        setSectors(sec);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const sorted = useMemo(
    () => sortSectors(sectors, sortKey, sortDir),
    [sectors, sortKey, sortDir]
  );

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  const colHeaders: { key: SortKey; label: string; align?: string }[] = [
    { key: "nace2", label: "NACE" },
    { key: "sector", label: "Sector" },
    { key: "companies", label: "Companies", align: "text-right" },
    { key: "revenue_m", label: "Revenue (M)", align: "text-right" },
    { key: "ebitda_m", label: "EBITDA (M)", align: "text-right" },
    { key: "med_margin", label: "Median Margin", align: "text-right" },
    { key: "med_fte", label: "Median FTE", align: "text-right" },
  ];

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Sector Statistics</h1>
        <p className="mt-1 text-sm text-slate-500">
          Aggregate metrics across all sectors in the database
        </p>
      </div>

      {/* Overview KPI cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        {KPI_META.map((kpi) => (
          <Card key={kpi.key} className="bg-white">
            <CardContent className="pt-5 pb-4 text-center">
              {loading ? (
                <>
                  <SkeletonBlock className="h-8 w-24 mx-auto mb-2" />
                  <SkeletonBlock className="h-3 w-20 mx-auto" />
                </>
              ) : (
                <>
                  <div className="text-2xl font-bold text-slate-900">
                    {overview ? kpi.fmt(overview[kpi.key] as number | null) : "\u2014"}
                  </div>
                  <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1">
                    {kpi.label}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Sector table */}
      <div>
        <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 border-l-2 border-indigo-600 pl-2 mb-4">
          Sector Breakdown
        </h2>
        <Card className="bg-white overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                {colHeaders.map((col) => (
                  <TableHead
                    key={col.key}
                    className={`cursor-pointer select-none whitespace-nowrap ${col.align ?? ""}`}
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
                sorted.map((row) => (
                  <TableRow key={row.nace2} className="hover:bg-indigo-50/40">
                    <TableCell className="font-medium">
                      <Link
                        href={`/screener?nace=${row.nace2}`}
                        className="text-indigo-600 hover:text-indigo-800 hover:underline"
                      >
                        {row.nace2}
                      </Link>
                    </TableCell>
                    <TableCell className="text-slate-700 max-w-[260px] truncate" title={row.sector}>
                      {row.sector}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {fmtNumber(row.companies)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {fmtEur(row.revenue_m != null ? row.revenue_m * 1e6 : null)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {fmtEur(row.ebitda_m != null ? row.ebitda_m * 1e6 : null)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {fmtPct(row.med_margin)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-sm">
                      {fmtNumber(row.med_fte)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </Card>
      </div>
    </div>
  );
}
