"use client";

import { useState } from "react";
import Link from "next/link";
import AdUnit from "@/components/ad-unit";
import { Card, CardContent } from "@/components/ui/card";
import { useTranslation } from "@/components/language-provider";
import {
  Search,
  SlidersHorizontal,
  Building,
  BarChart,
  UserSearch,
  Sparkles,
  Heart,
  BookOpen,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

export default function Dashboard() {
  const { t } = useTranslation();

  const [showAllFeatures, setShowAllFeatures] = useState(false);

  const WHATS_NEW = [
    { label: "AI Company Insights", desc: "One-click AI analysis with business description, products, customers & market position", color: "bg-indigo-400" },
    { label: "AI-Enhanced Similar Companies", desc: "LLM-curated peer ranking with business similarity explanations", color: "bg-emerald-400" },
    { label: "AI Publication Summaries", desc: "AI-generated summary of recent Staatsblad publications", color: "bg-cyan-400" },
    { label: "Multi-NACE Screener", desc: "Select multiple NACE codes with chips/tags for cross-sector screening", color: "bg-amber-400" },
    { label: "Company Profile Redesign", desc: "Faster page with 10 dedicated tabs for financials, structure & benchmarks", color: "bg-sky-400" },
    { label: "Full Excel & PDF Export", desc: "Download complete company profiles with all financials", color: "bg-violet-400" },
    { label: "Smart Screener Filters", desc: "Save and load your screener filter presets", color: "bg-rose-400" },
    { label: "DuckDuckGo URL Discovery", desc: "Automatic company website and LinkedIn detection via web search", color: "bg-teal-400" },
    { label: "Staatsblad Admin Extraction", desc: "Auto-extract board members from Belgian Official Gazette PDFs", color: "bg-orange-400" },
    { label: "Sector Benchmarking", desc: "See how a company ranks within its sector", color: "bg-pink-400" },
  ];
  const visibleFeatures = showAllFeatures ? WHATS_NEW : WHATS_NEW.slice(0, 3);

  const QUICK_ACCESS = [
    { href: "/search", title: t("home.quickAccessCards.searchTitle") || "Search", desc: t("home.quickAccessCards.searchDesc") || "Find companies by name, CBE, or keyword", icon: Search },
    { href: "/screener", title: t("home.quickAccessCards.screenerTitle"), desc: t("home.quickAccessCards.screenerDesc"), icon: SlidersHorizontal },
    { href: "/company", title: t("home.quickAccessCards.companyTitle"), desc: t("home.quickAccessCards.companyDesc"), icon: Building },
    { href: "/stats", title: t("home.quickAccessCards.statsTitle"), desc: t("home.quickAccessCards.statsDesc"), icon: BarChart },
    { href: "/people", title: t("home.quickAccessCards.peopleTitle"), desc: t("home.quickAccessCards.peopleDesc"), icon: UserSearch },
    { href: "/favourites", title: t("home.quickAccessCards.favouritesTitle") || "Favourites", desc: t("home.quickAccessCards.favouritesDesc") || "Your saved companies", icon: Heart },
    // Graveyard removed from Quick Access per user request
  ];

  return (
    <div className="space-y-8">
      {/* Beta notice */}
      <div className="rounded-lg border border-indigo-100 bg-indigo-50/50 px-4 py-3">
        <p className="text-sm text-slate-600">
          <span className="font-semibold text-indigo-600">{t("home.betaNotice")}</span>{" "}
          {t("home.betaBody")}
        </p>
      </div>

      {/* What's New */}
      <div>
        <Card className="bg-white">
          <CardContent className="pt-4 pb-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Sparkles className="h-3.5 w-3.5 text-indigo-500" />
                <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">{t("home.whatsNew")}</h2>
              </div>
              <div className="flex items-center gap-3">
                <Link href="/guide" className="inline-flex items-center gap-1 text-[11px] font-medium text-indigo-500 hover:text-indigo-700 transition-colors">
                  <BookOpen className="w-3 h-3" /> User Guide
                </Link>
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-2">
              {visibleFeatures.map((item) => (
                <div key={item.label} className="flex items-start gap-2 py-1">
                  <span className={`mt-1.5 h-1.5 w-1.5 rounded-full shrink-0 ${item.color}`} />
                  <div>
                    <span className="text-xs font-semibold text-slate-700">{item.label}</span>
                    <span className="text-xs text-slate-400 ml-1">— {item.desc}</span>
                  </div>
                </div>
              ))}
            </div>
            {WHATS_NEW.length > 3 && (
              <button
                onClick={() => setShowAllFeatures(!showAllFeatures)}
                className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-indigo-500 hover:text-indigo-700 transition-colors"
              >
                {showAllFeatures ? <><ChevronUp className="w-3 h-3" /> Show less</> : <><ChevronDown className="w-3 h-3" /> Show all {WHATS_NEW.length} features</>}
              </button>
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

      {/* Ad placement: between quick access and stats */}
      <AdUnit slot="3722838377" format="fluid" className="rounded-lg" />

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
