"use client";

import Link from "next/link";
import {
  TrendingUp,
  Users,
  Building2,
  Search,
  BarChart3,
  Network,
} from "lucide-react";

/* #18 Glassmorphism marketing/demo page.
 *
 * Routed at /showcase. Separate from the product routes so it can have
 * its own bold visual language (animated gradient background, frosted
 * translucent cards) without polluting the app shell.
 */

const FEATURES = [
  {
    icon: Search,
    title: "Search 170k+ Belgian companies",
    body: "Name, CBE, address, sector, postal code. Typo-tolerant, fuzzy, fast.",
  },
  {
    icon: BarChart3,
    title: "NBB-grade financials",
    body: "Full P&L, balance sheet, cash flow, EBITDA drill-down. Rubric 9900 to 9904, the way auditors look at it.",
  },
  {
    icon: Users,
    title: "People + mandates",
    body: "Who sits on which board, starting when, ending when. Sourced from KBO + Belgisch Staatsblad.",
  },
  {
    icon: Network,
    title: "Ownership networks",
    body: "Interactive spiderweb of shareholders, directors, subsidiaries — up to 4 degrees out.",
  },
  {
    icon: Building2,
    title: "Sector benchmarks",
    body: "Compare any company to its NACE peers on margin, growth, working capital.",
  },
  {
    icon: TrendingUp,
    title: "Built for PE deal sourcing",
    body: "Screener + watchlists + project boards. Export to Excel / PDF in one click.",
  },
];

export default function ShowcasePage() {
  return (
    <div className="relative min-h-screen overflow-hidden bg-gradient-to-br from-indigo-100 via-slate-100 to-indigo-50">
      {/* Decorative blurred blobs — the whole reason for glassmorphism. */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-32 -left-32 h-96 w-96 rounded-full bg-indigo-400/40 blur-3xl" />
        <div className="absolute top-1/3 -right-32 h-[32rem] w-[32rem] rounded-full bg-violet-400/40 blur-3xl" />
        <div className="absolute bottom-0 left-1/3 h-80 w-80 rounded-full bg-emerald-300/30 blur-3xl" />
      </div>

      <div className="relative z-10 mx-auto max-w-[1100px] px-6 py-16">
        {/* Top nav strip */}
        <div className="flex items-center justify-between mb-16">
          <Link
            href="/"
            className="text-xl font-bold text-slate-900"
          >
            DataSnoop
          </Link>
          <div className="flex items-center gap-3 text-sm">
            <Link
              href="/search"
              className="px-4 py-2 rounded-full bg-white/40 backdrop-blur-md border border-white/60 text-slate-700 hover:bg-white/60 transition-colors"
            >
              Try the search
            </Link>
            <Link
              href="/login"
              className="px-4 py-2 rounded-full bg-slate-900 text-white hover:bg-indigo-600 transition-colors"
            >
              Sign in
            </Link>
          </div>
        </div>

        {/* Hero */}
        <div className="mb-20">
          <div className="inline-block rounded-full bg-white/40 backdrop-blur-md border border-white/60 px-3 py-1 text-[11px] text-slate-700 mb-4">
            DataSnoop · Belgian company intelligence
          </div>
          <h1 className="text-4xl md:text-6xl font-bold text-slate-900 leading-tight max-w-3xl">
            Every Belgian company,<br />
            <span className="bg-gradient-to-r from-indigo-600 to-violet-600 bg-clip-text text-transparent">
              every filing, every mandate.
            </span>
          </h1>
          <p className="mt-5 text-base md:text-lg text-slate-600 max-w-2xl">
            A self-hosted Belfirst alternative for PE analysts: KBO registry +
            NBB annual accounts + Belgisch Staatsblad — scored, networked, and
            searchable in under 200 ms.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              href="/search?q=colruyt"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-full bg-slate-900 text-white hover:bg-indigo-600 transition-colors font-medium"
            >
              See a live example <Search className="h-4 w-4" />
            </Link>
            <Link
              href="/use-cases.html"
              className="inline-flex items-center gap-2 px-6 py-3 rounded-full bg-white/50 backdrop-blur-md border border-white/70 text-slate-700 hover:bg-white/70 transition-colors font-medium"
            >
              Use cases
            </Link>
          </div>
        </div>

        {/* Feature cards — frosted glass tiles */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {FEATURES.map((f, i) => (
            <div
              key={i}
              className="rounded-2xl bg-white/45 backdrop-blur-xl border border-white/60 p-5 shadow-[0_8px_32px_rgba(31,38,135,0.08)] hover:bg-white/60 transition-colors"
            >
              <div className="h-9 w-9 rounded-lg bg-gradient-to-br from-indigo-400 to-violet-500 text-white flex items-center justify-center mb-3">
                <f.icon className="h-4.5 w-4.5" strokeWidth={2} />
              </div>
              <h3 className="text-sm font-semibold text-slate-900 mb-1">{f.title}</h3>
              <p className="text-[13px] text-slate-600 leading-relaxed">{f.body}</p>
            </div>
          ))}
        </div>

        {/* Proof strip */}
        <div className="mt-16 rounded-2xl bg-white/40 backdrop-blur-xl border border-white/60 p-6 md:p-8">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6 text-center">
            <Stat value="170k" label="Belgian companies" />
            <Stat value="15 yrs" label="NBB filing history" />
            <Stat value="Daily" label="KBO + Staatsblad refresh" />
            <Stat value="<200 ms" label="p95 search latency" />
          </div>
        </div>

        <p className="mt-16 text-center text-xs text-slate-500">
          <Link href="/status" className="hover:text-indigo-600">
            System status
          </Link>
          <span className="mx-2">·</span>
          <Link href="/privacy" className="hover:text-indigo-600">
            Privacy
          </Link>
          <span className="mx-2">·</span>
          <Link href="/terms" className="hover:text-indigo-600">
            Terms
          </Link>
        </p>
      </div>
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="text-2xl md:text-3xl font-bold bg-gradient-to-r from-indigo-600 to-violet-600 bg-clip-text text-transparent">
        {value}
      </div>
      <div className="mt-1 text-[11px] uppercase tracking-wider text-slate-500">
        {label}
      </div>
    </div>
  );
}
