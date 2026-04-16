"use client";

import Link from "next/link";
import {
  Search,
  SlidersHorizontal,
  Building,
  BarChart,
  UserSearch,
  Sparkles,
  Heart,
  FileText,
  Users,
  Scale,
  Download,
  BookOpen,
} from "lucide-react";

const sections = [
  {
    icon: Search,
    title: "Search",
    href: "/search",
    body: "Search for any Belgian company by name, CBE number, or keyword. Results appear instantly as you type, powered by trigram fuzzy matching. Click any result to open the full company profile.",
  },
  {
    icon: SlidersHorizontal,
    title: "Screener",
    href: "/screener",
    body: "Filter the entire database by financial metrics: revenue, EBIT, EBITDA, FTE, margin, leverage, and YoY growth rates. Select multiple NACE codes to screen across sectors. Save your filter presets for quick re-use. Export results to CSV.",
  },
  {
    icon: Building,
    title: "Company Profile",
    href: "/company",
    body: "Each company has a dedicated profile with 10 tabs: Summary, P&L, Balance Sheet, Credit Analysis, Administrators, Structure (shareholders & subsidiaries), Sector Benchmark, Similar Companies, Publications, and Network Graph. Financial data comes from NBB annual filings.",
  },
  {
    icon: Sparkles,
    title: "AI Insights",
    body: "Click the sparkle button on any company profile to generate AI-powered analysis. This includes: business description, products & services, customer base, market position, and key management. The AI also discovers the company website and LinkedIn page automatically.",
  },
  {
    icon: Users,
    title: "Similar Companies",
    body: "The Similar Companies tab shows up to 100 peers in the same NACE sector with comparable revenue. Click 'AI Rank' to re-rank using AI for true business similarity with explanations. Use 'Compare all' to see a side-by-side financial comparison.",
  },
  {
    icon: FileText,
    title: "Publications",
    body: "The Publications tab shows all Staatsblad (Belgian Official Gazette) publications: board changes, capital increases, mergers, dissolutions, and more. Click 'Summarize publications' for an AI-generated overview of recent corporate activity.",
  },
  {
    icon: BarChart,
    title: "Sector Statistics",
    href: "/stats",
    body: "Explore sector-level statistics by NACE code. See median revenue, EBITDA margins, company counts, and distribution charts. Useful for understanding industry benchmarks before evaluating specific companies.",
  },
  {
    icon: UserSearch,
    title: "People Search",
    href: "/people",
    body: "Search for individuals across all Belgian companies. Find administrators, shareholders, and beneficial owners. Click a person's name to see all their corporate roles and mandates.",
  },
  {
    icon: Heart,
    title: "Favourites",
    href: "/favourites",
    body: "Save companies to your favourites list for quick access. Your favourites are stored in your account and sync across devices. Use this to build a shortlist of target companies for deal sourcing.",
  },
  {
    icon: Scale,
    title: "Company Comparison",
    href: "/compare",
    body: "Compare multiple companies side-by-side on all financial metrics. Access this from the Similar Companies tab ('Compare all') or by manually selecting companies. Great for benchmarking targets against peers.",
  },
  {
    icon: Download,
    title: "Export",
    body: "Export data from any page: screener results to CSV, company profiles to Excel or PDF, publication lists to CSV. Look for the export button in the top-right of tables and cards.",
  },
];

export default function GuidePage() {
  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <div className="flex items-center gap-3 mb-2">
        <BookOpen className="w-5 h-5 text-indigo-500" />
        <h1 className="text-lg font-bold text-slate-900">User Guide</h1>
      </div>
      <p className="text-sm text-slate-500 -mt-4">
        DataSnoop is a Belgian company intelligence platform combining KBO registry data with NBB annual accounts. This guide covers every feature.
      </p>

      <div className="space-y-4">
        {sections.map((s) => {
          const Icon = s.icon;
          return (
            <div key={s.title} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="flex items-center gap-2 mb-2">
                <Icon className="w-4 h-4 text-indigo-500 shrink-0" />
                <h2 className="text-sm font-semibold text-slate-900">
                  {s.href ? (
                    <Link href={s.href} className="hover:text-indigo-600 hover:underline transition-colors">
                      {s.title}
                    </Link>
                  ) : s.title}
                </h2>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed pl-6">{s.body}</p>
            </div>
          );
        })}
      </div>

      <div className="text-center py-4">
        <Link href="/" className="text-xs text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
          Back to Dashboard
        </Link>
      </div>
    </div>
  );
}
