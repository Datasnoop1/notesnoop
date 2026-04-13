"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { getDashboard, type DashboardKPIs } from "@/lib/api";
import { fmtNumber } from "@/lib/format";
import {
  Building2,
  BarChart3,
  FileText,
  Users,
  Calendar,
  Search,
  Building,
  BarChart,
  UserSearch,
} from "lucide-react";

function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse bg-slate-200 rounded ${className}`} />;
}

const KPI_META = [
  { key: "enterprise_count" as const, label: "Active Enterprises", icon: Building2 },
  { key: "financial_count" as const, label: "Companies with Financials", icon: BarChart3 },
  { key: "filing_count" as const, label: "Filings Loaded", icon: FileText },
  { key: "admin_count" as const, label: "Administrators Indexed", icon: Users },
];

const QUICK_ACCESS = [
  { href: "/screener", title: "Screener", desc: "Filter by sector, revenue, EBITDA, FTE, region", icon: Search },
  { href: "/company", title: "Company", desc: "Search by name or CBE -- financials, structure, filings", icon: Building },
  { href: "/stats", title: "Stats", desc: "Sector benchmarks, margins, leverage, geography", icon: BarChart },
  { href: "/people", title: "People", desc: "Find administrators and shareholders by name", icon: UserSearch },
];


export default function Dashboard() {
  const [kpis, setKpis] = useState<DashboardKPIs | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getDashboard()
      .then(setKpis)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-4">
      {/* Spacer */}
      <div />

      {/* KPI Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {KPI_META.map((kpi) => {
          const Icon = kpi.icon;
          return (
            <Card key={kpi.key} className="bg-white">
              <CardContent className="pt-3 pb-3 text-center">
                {loading ? (
                  <><Skeleton className="h-7 w-24 mx-auto mb-1" /><Skeleton className="h-3 w-20 mx-auto" /></>
                ) : (
                  <>
                    <Icon className="w-4 h-4 text-indigo-500 mx-auto mb-1" />
                    <div className="text-xl font-bold text-slate-900">{kpis ? fmtNumber(kpis[kpi.key]) : "—"}</div>
                    <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-0.5">{kpi.label}</div>
                  </>
                )}
              </CardContent>
            </Card>
          );
        })}
        <Card className="bg-white">
          <CardContent className="pt-3 pb-3 text-center">
            {loading ? (
              <><Skeleton className="h-7 w-24 mx-auto mb-1" /><Skeleton className="h-3 w-20 mx-auto" /></>
            ) : (
              <>
                <Calendar className="w-4 h-4 text-indigo-500 mx-auto mb-1" />
                <div className="text-xl font-bold text-slate-900">{kpis?.snapshot_date || "—"}</div>
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-0.5">Snapshot Date</div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Quick Access */}
      <div>
        <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 border-l-2 border-indigo-600 pl-2 mb-3">Quick Access</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {QUICK_ACCESS.map((item) => {
            const Icon = item.icon;
            return (
              <Link key={item.href} href={item.href}>
                <Card className="bg-white hover:shadow-md transition-shadow cursor-pointer border-l-4 border-l-indigo-600 h-full">
                  <CardContent className="pt-3 pb-3">
                    <h3 className="font-semibold text-sm text-slate-900">
                      <Icon className="w-3.5 h-3.5 inline mr-1.5" />
                      {item.title}
                    </h3>
                    <p className="text-xs text-slate-500 mt-0.5">{item.desc}</p>
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      </div>

    </div>
  );
}
