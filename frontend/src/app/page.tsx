"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getDashboard, type DashboardKPIs } from "@/lib/api";
import { fmtNumber } from "@/lib/format";
import { useTranslation } from "@/components/language-provider";
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
  Sparkles,
} from "lucide-react";

function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse bg-slate-200 rounded ${className}`} />;
}

export default function Dashboard() {
  const { t } = useTranslation();
  const [kpis, setKpis] = useState<DashboardKPIs | null>(null);
  const [loading, setLoading] = useState(true);

  const KPI_META = [
    { key: "enterprise_count" as const, label: t("home.kpi.activeEnterprises"), icon: Building2 },
    { key: "financial_count" as const, label: t("home.kpi.companiesWithFinancials"), icon: BarChart3 },
    { key: "filing_count" as const, label: t("home.kpi.filingsLoaded"), icon: FileText },
    { key: "admin_count" as const, label: t("home.kpi.administratorsIndexed"), icon: Users },
  ];

  const WHATS_NEW = [
    { label: t("home.whatsNewItems.unifiedSearch"), desc: t("home.whatsNewItems.unifiedSearchDesc"), color: "bg-indigo-400" },
    { label: t("home.whatsNewItems.sectorBenchmarking"), desc: t("home.whatsNewItems.sectorBenchmarkingDesc"), color: "bg-emerald-400" },
    { label: t("home.whatsNewItems.smartFilters"), desc: t("home.whatsNewItems.smartFiltersDesc"), color: "bg-amber-400" },
    { label: t("home.whatsNewItems.dataAlerts"), desc: t("home.whatsNewItems.dataAlertsDesc"), color: "bg-rose-400" },
    { label: t("home.whatsNewItems.customerSupplierLists"), desc: t("home.whatsNewItems.customerSupplierListsDesc"), color: "bg-sky-400" },
    { label: t("home.whatsNewItems.fullExport"), desc: t("home.whatsNewItems.fullExportDesc"), color: "bg-violet-400" },
  ];

  const QUICK_ACCESS = [
    { href: "/screener", title: t("home.quickAccessCards.screenerTitle"), desc: t("home.quickAccessCards.screenerDesc"), icon: Search },
    { href: "/company", title: t("home.quickAccessCards.companyTitle"), desc: t("home.quickAccessCards.companyDesc"), icon: Building },
    { href: "/stats", title: t("home.quickAccessCards.statsTitle"), desc: t("home.quickAccessCards.statsDesc"), icon: BarChart },
    { href: "/people", title: t("home.quickAccessCards.peopleTitle"), desc: t("home.quickAccessCards.peopleDesc"), icon: UserSearch },
  ];

  useEffect(() => {
    getDashboard()
      .then(setKpis)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-8">
      {/* Beta notice */}
      <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-4 py-3">
        <p className="text-sm text-slate-600">
          <span className="font-semibold text-indigo-600">{t("home.betaNotice")}</span>{" "}
          {t("home.betaBody")}
        </p>
      </div>

      {/* Search section */}
      <Link href="/search">
        <Card className="bg-white hover:shadow-md hover:border-indigo-200 transition-all cursor-pointer group">
          <CardContent className="pt-4 pb-4">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-indigo-50 text-indigo-600 group-hover:bg-indigo-100 transition-colors">
                <Search className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-slate-900">{t("home.searchTitle")}</h3>
                <p className="text-xs text-slate-400 mt-0.5">{t("home.searchDesc")}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </Link>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 pt-2">
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
                <div className="text-[11px] uppercase tracking-wide text-slate-400 mt-0.5">{t("home.snapshotDate")}</div>
              </>
            )}
          </CardContent>
        </Card>
      </div>


      {/* Quick Access */}
      <div>
        <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500 border-l-2 border-indigo-600 pl-2 mb-3">{t("home.quickAccess")}</h2>
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

      {/* What's New */}
      <div>
        <Card className="bg-white">
          <CardContent className="pt-4 pb-4">
            <div className="flex items-center gap-2 mb-3">
              <Sparkles className="h-3.5 w-3.5 text-indigo-500" />
              <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">{t("home.whatsNew")}</h2>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2">
              {WHATS_NEW.map((item) => (
                <div key={item.label} className="flex items-start gap-2 py-1">
                  <span className={`mt-1.5 h-1.5 w-1.5 rounded-full shrink-0 ${item.color}`} />
                  <div>
                    <span className="text-xs font-semibold text-slate-700">{item.label}</span>
                    <span className="text-xs text-slate-400 ml-1">— {item.desc}</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Data Stats teaser */}
      <div>
        <Link href="/stats">
          <Card className="bg-gradient-to-r from-indigo-50 to-slate-50 border-indigo-100 hover:shadow-md transition-shadow cursor-pointer">
            <CardContent className="pt-4 pb-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <BarChart className="h-4 w-4 text-indigo-500" />
                    <h3 className="text-sm font-semibold text-slate-900">{t("home.marketStats")}</h3>
                  </div>
                  <p className="text-xs text-slate-500">{t("home.marketStatsDesc")}</p>
                </div>
                <span className="text-xs text-indigo-500 font-medium shrink-0 ml-4">{t("home.explore")} →</span>
              </div>
            </CardContent>
          </Card>
        </Link>
      </div>

    </div>
  );
}
