"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  getDashboard,
  getTopCompanies,
  type DashboardKPIs,
  type TopCompany,
} from "@/lib/api";
import { fmtEur, fmtCbe, fmtPct, fmtNumber } from "@/lib/format";

function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse bg-slate-200 rounded ${className}`} />;
}

const KPI_META = [
  { key: "enterprise_count" as const, label: "Active Enterprises" },
  { key: "financial_count" as const, label: "Companies with Financials" },
  { key: "filing_count" as const, label: "Filings Loaded" },
  { key: "admin_count" as const, label: "Administrators Indexed" },
];

const QUICK_ACCESS = [
  { href: "/screener", title: "Screener", desc: "Filter by sector, revenue, EBITDA, FTE, region" },
  { href: "/company", title: "Company", desc: "Search by name or CBE -- financials, structure, filings" },
  { href: "/stats", title: "Stats", desc: "Sector benchmarks, margins, leverage, geography" },
  { href: "/people", title: "People", desc: "Find administrators and shareholders by name" },
];

export default function Dashboard() {
  const [kpis, setKpis] = useState<DashboardKPIs | null>(null);
  const [top, setTop] = useState<TopCompany[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getDashboard(), getTopCompanies("revenue", 15)])
      .then(([d, t]) => { setKpis(d); setTop(t); })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-8">
      {/* Hero */}
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Belgian Company Intelligence</h1>
        <p className="text-slate-500 mt-1">KBO registry &middot; NBB annual accounts</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        {KPI_META.map((kpi) => (
          <Card key={kpi.key} className="bg-white">
            <CardContent className="pt-5 pb-4 text-center">
              {loading ? (
                <><Skeleton className="h-8 w-24 mx-auto mb-2" /><Skeleton className="h-3 w-20 mx-auto" /></>
              ) : (
                <>
                  <div className="text-2xl font-bold text-slate-900">{kpis ? fmtNumber(kpis[kpi.key]) : "—"}</div>
                  <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1">{kpi.label}</div>
                </>
              )}
            </CardContent>
          </Card>
        ))}
        <Card className="bg-white">
          <CardContent className="pt-5 pb-4 text-center">
            {loading ? (
              <><Skeleton className="h-8 w-24 mx-auto mb-2" /><Skeleton className="h-3 w-20 mx-auto" /></>
            ) : (
              <>
                <div className="text-2xl font-bold text-slate-900">{kpis?.snapshot_date || "—"}</div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-1">Snapshot Date</div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Quick Access */}
      <div>
        <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 border-l-2 border-indigo-600 pl-2 mb-4">Quick Access</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {QUICK_ACCESS.map((item) => (
            <Link key={item.href} href={item.href}>
              <Card className="bg-white hover:shadow-md transition-shadow cursor-pointer border-l-4 border-l-indigo-600 h-full">
                <CardContent className="pt-4 pb-4">
                  <h3 className="font-semibold text-slate-900">{item.title}</h3>
                  <p className="text-sm text-slate-500 mt-1">{item.desc}</p>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      </div>

      {/* Top Companies */}
      <div>
        <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 border-l-2 border-indigo-600 pl-2 mb-4">Largest Companies by Revenue</h2>
        <Card className="bg-white overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Company</TableHead>
                <TableHead>Sector</TableHead>
                <TableHead className="text-right">Revenue</TableHead>
                <TableHead className="text-right">EBITDA</TableHead>
                <TableHead className="text-right">Margin</TableHead>
                <TableHead className="text-right">FTE</TableHead>
                <TableHead className="text-right">FY</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading
                ? Array.from({ length: 8 }).map((_, i) => (
                    <TableRow key={i}>
                      {Array.from({ length: 7 }).map((_, j) => (
                        <TableCell key={j}><Skeleton className="h-4 w-20" /></TableCell>
                      ))}
                    </TableRow>
                  ))
                : top.map((c) => (
                    <TableRow key={c.cbe} className="hover:bg-slate-50">
                      <TableCell>
                        <Link href={`/company/${c.cbe}`} className="text-indigo-600 hover:underline font-medium">
                          {c.name || fmtCbe(c.cbe)}
                        </Link>
                      </TableCell>
                      <TableCell className="text-slate-500 text-sm max-w-[200px] truncate">{c.sector || "—"}</TableCell>
                      <TableCell className="text-right font-mono text-sm">{fmtEur(c.revenue)}</TableCell>
                      <TableCell className="text-right font-mono text-sm">{fmtEur(c.ebitda)}</TableCell>
                      <TableCell className="text-right font-mono text-sm">{fmtPct(c.ebitda_margin_pct)}</TableCell>
                      <TableCell className="text-right font-mono text-sm">{fmtNumber(c.fte_total)}</TableCell>
                      <TableCell className="text-right text-sm">{c.fiscal_year || "—"}</TableCell>
                    </TableRow>
                  ))}
            </TableBody>
          </Table>
        </Card>
      </div>
    </div>
  );
}
