"use client";

import React from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { fmtEur, fmtCbe, fmtPct, fmtNumber } from "@/lib/format";
import {
  ExternalLink,
  ChevronRight,
  Users,
  Briefcase,
  GitBranch,
  FileText,
  BarChart3,
  DollarSign,
  TrendingUp,
  Percent,
  Activity,
  Calendar,
  UserCheck,
  Newspaper,
  Loader2,
  Sparkles,
  Globe,
} from "lucide-react";
import { SearchableText, GoogleSearchLink } from "@/components/google-search-link";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type {
  CompanyDetail,
  FinancialsData,
  StructureData,
} from "../types";
import { renderDelta, cleanCbe, ChartTooltip } from "../helpers";

/* ---------- props ---------- */

export interface SummaryTabProps {
  detail: CompanyDetail;
  financials: FinancialsData | null;
  structure: StructureData | null;
  cbe: string;
  activeTab: string;
  // AI enrichment
  aiSummary: string | null;
  aiLoading: boolean;
  aiError: string | null;
  onEnrichCompany: () => void;
  // Website/LinkedIn scrape
  websiteScrape: { summary: string; products: string; employees: string; key_people: string; website_url: string } | null;
  websiteScrapeLoading: boolean;
  websiteError: string | null;
  onScrapeWebsite: () => void;
  linkedinScrape: { summary: string; employee_count: string; industry: string; specialties: string; linkedin_url: string } | null;
  linkedinScrapeLoading: boolean;
  linkedinError: string | null;
  onScrapeLinkedIn: () => void;
  // Collapsible sections
  collapsedSections: Record<string, boolean>;
  toggleSection: (key: string) => void;
  // Tab navigation
  setActiveTab: (tab: string) => void;
}

/* ---------- inline helpers ---------- */

function yoyChange(curr: number | null, previous: number | null): { pct: number; direction: "up" | "down" | "flat" } | null {
  if (curr == null || previous == null || previous === 0) return null;
  const pct = ((curr - previous) / Math.abs(previous)) * 100;
  return { pct, direction: pct > 0.5 ? "up" : pct < -0.5 ? "down" : "flat" };
}

function changeArrow(change: { pct: number; direction: "up" | "down" | "flat" } | null, goodIfUp = true) {
  if (!change) return null;
  const isGood = (change.direction === "up" && goodIfUp) || (change.direction === "down" && !goodIfUp);
  const color = change.direction === "flat" ? "text-slate-400" : isGood ? "text-emerald-500" : "text-rose-400";
  const arrow = change.direction === "up" ? "\u2191" : change.direction === "down" ? "\u2193" : "\u2192";
  return (
    <span className={`text-xs font-medium ${color}`}>
      {arrow} {Math.abs(change.pct).toFixed(1)}%
    </span>
  );
}

function marginColorClass(v: number | null): string {
  if (v == null) return "text-slate-900";
  if (v >= 15) return "text-emerald-600";
  if (v >= 5) return "text-amber-600";
  if (v < 0) return "text-rose-400";
  return "text-slate-900";
}

function pillColor(type: "leverage" | "margin" | "growth", value: number | null): string {
  if (value == null) return "bg-slate-50 text-slate-400 border-slate-100";
  if (type === "leverage") {
    if (value < 3) return "bg-emerald-50 text-emerald-700 border-emerald-100";
    if (value <= 5) return "bg-amber-50 text-amber-700 border-amber-100";
    return "bg-rose-50 text-rose-500 border-rose-100";
  }
  if (type === "margin") {
    if (value >= 15) return "bg-emerald-50 text-emerald-700 border-emerald-100";
    if (value >= 5) return "bg-amber-50 text-amber-700 border-amber-100";
    return "bg-rose-50 text-rose-500 border-rose-100";
  }
  // growth
  if (value > 2) return "bg-emerald-50 text-emerald-700 border-emerald-100";
  if (value >= -2) return "bg-slate-50 text-slate-500 border-slate-100";
  return "bg-rose-50 text-rose-500 border-rose-100";
}

function shortDate(d: string | null): string {
  if (!d) return "";
  const date = new Date(d);
  return date.toLocaleDateString("en-GB", { month: "short", year: "numeric" });
}

/* ---------- component ---------- */

export function SummaryTab({
  detail,
  financials,
  structure,
  cbe,
  aiSummary,
  aiLoading,
  aiError,
  onEnrichCompany,
  websiteScrape,
  websiteScrapeLoading,
  websiteError,
  onScrapeWebsite,
  linkedinScrape,
  linkedinScrapeLoading,
  linkedinError,
  onScrapeLinkedIn,
  setActiveTab,
}: SummaryTabProps) {
  const sorted = [...(financials?.summary ?? [])].sort((a, b) => b.fiscal_year - a.fiscal_year);
  const latest = sorted[0] ?? null;
  const prev = sorted[1] ?? null;

  const currentAdmins = (structure?.administrators || []).filter(
    (a) => !a.mandate_end || a.mandate_end === "" || new Date(a.mandate_end) > new Date()
  );

  // Credit ratios
  let netDebtEbitda: number | null = null;
  if (latest) {
    const grossDebt = (latest.lt_financial_debt ?? 0) + (latest.st_financial_debt ?? 0);
    const netDebt = grossDebt - (latest.cash ?? 0) - (latest.current_investments ?? 0);
    netDebtEbitda = latest.ebitda && latest.ebitda !== 0 ? netDebt / latest.ebitda : null;
  }

  const revenueYoy = yoyChange(latest?.revenue ?? null, prev?.revenue ?? null);
  const ebitdaYoy = yoyChange(latest?.ebitda ?? null, prev?.ebitda ?? null);
  const fteYoy = yoyChange(latest?.fte_total ?? null, prev?.fte_total ?? null);

  // Sparkline data (last 5 years)
  const sparkData = sorted.slice(0, 5).reverse().map((r) => ({
    fy: String(r.fiscal_year),
    Revenue: r.revenue,
    EBITDA: r.ebitda,
  }));

  return (
    <div className="space-y-6">
      {/* Row 1: KPIs (left) + Trend chart (right) */}
      {latest && (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
          {/* Left: compact KPI list */}
          <div className="lg:col-span-2 rounded-xl border border-slate-100 bg-white p-4">
            <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <BarChart3 className="h-3 w-3" /> Key Financials
              {latest.fiscal_year && <span className="text-slate-300 font-mono">FY{latest.fiscal_year}</span>}
            </h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <DollarSign className="h-3.5 w-3.5 text-slate-400" /> Revenue
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-900 font-mono">{fmtEur(latest.revenue)}</span>
                  {changeArrow(revenueYoy)}
                </div>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <TrendingUp className="h-3.5 w-3.5 text-slate-400" /> EBITDA
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-900 font-mono">{fmtEur(latest.ebitda)}</span>
                  {changeArrow(ebitdaYoy)}
                </div>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <Percent className="h-3.5 w-3.5 text-slate-400" /> Margin
                </div>
                <span className={`text-sm font-semibold font-mono ${marginColorClass(latest.ebitda_margin_pct)}`}>{fmtPct(latest.ebitda_margin_pct)}</span>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <Users className="h-3.5 w-3.5 text-slate-400" /> Employees
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-900 font-mono">{latest.fte_total != null ? fmtNumber(latest.fte_total) : "\u2014"}</span>
                  {changeArrow(fteYoy)}
                </div>
              </div>
            </div>
            {/* Health pills */}
            <div className="flex flex-wrap gap-1.5 mt-4 pt-3 border-t border-slate-50">
              <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${pillColor("leverage", netDebtEbitda)}`}>
                {netDebtEbitda != null && isFinite(netDebtEbitda) ? `${netDebtEbitda.toFixed(1)}x leverage` : "\u2014 leverage"}
              </span>
              <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${pillColor("growth", revenueYoy?.pct ?? null)}`}>
                {revenueYoy ? `${revenueYoy.pct > 0 ? "+" : ""}${revenueYoy.pct.toFixed(0)}% growth` : "\u2014 growth"}
              </span>
            </div>
          </div>

          {/* Right: sparkline chart */}
          <div className="lg:col-span-3 rounded-xl border border-slate-100 bg-white p-4">
            <div className="flex items-baseline justify-between mb-2">
              <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                <Activity className="h-3 w-3" /> Trend
              </h3>
              <button type="button" onClick={() => setActiveTab("pnl")} className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
                Full P&L →
              </button>
            </div>
            {sparkData.length >= 2 ? (
              <>
                <ResponsiveContainer width="100%" height={130}>
                  <LineChart data={sparkData} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
                    <XAxis dataKey="fy" tick={{ fontSize: 10, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
                    <YAxis hide />
                    <Tooltip content={<ChartTooltip />} />
                    <Line type="monotone" dataKey="Revenue" stroke="#6366f1" strokeWidth={2} dot={{ r: 2, fill: "#6366f1" }} />
                    <Line type="monotone" dataKey="EBITDA" stroke="#06b6d4" strokeWidth={2} dot={{ r: 2, fill: "#06b6d4" }} strokeDasharray="4 2" />
                  </LineChart>
                </ResponsiveContainer>
                <div className="flex items-center gap-4 mt-1">
                  <div className="flex items-center gap-1.5">
                    <span className="inline-block h-0.5 w-4 rounded bg-indigo-500" />
                    <span className="text-[10px] text-slate-400">Revenue</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="inline-block h-0.5 w-4 rounded bg-cyan-500" />
                    <span className="text-[10px] text-slate-400">EBITDA</span>
                  </div>
                </div>
              </>
            ) : (
              <div className="flex items-center justify-center h-[130px] text-xs text-slate-300">Not enough years for a trend</div>
            )}
          </div>
        </div>
      )}

      {/* Key People + Shareholders + Publications + Subsidiaries — 4 columns */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        {/* Key People */}
        <div className="rounded-xl border border-slate-100 bg-white p-4">
          <div className="flex items-baseline justify-between mb-3">
            <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <UserCheck className="h-3 w-3" /> Key People
              {currentAdmins.length > 0 && <span className="text-slate-300">({currentAdmins.length})</span>}
            </h3>
            {currentAdmins.length > 0 && (
              <button type="button" onClick={() => setActiveTab("administrators")} className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
                View all →
              </button>
            )}
          </div>
          {currentAdmins.length === 0 ? (
            <div className="flex items-center justify-center py-6 text-xs text-slate-300">
              <Users className="h-4 w-4 mr-2" /> No administrator data
            </div>
          ) : (
            <div className="space-y-2">
              {currentAdmins.slice(0, 6).map((a, i) => {
                const adminCbe = cleanCbe(a.identifier);
                return (
                  <div key={`${a.name}-${i}`} className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-50 transition-colors">
                    <div className="h-8 w-8 rounded-full bg-indigo-50 flex items-center justify-center text-[10px] font-bold text-indigo-600 shrink-0">
                      {(a.name || "?").slice(0, 2).toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      {adminCbe ? (
                        <Link href={`/company/${adminCbe}`} className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline font-medium truncate block">
                          {a.name}
                        </Link>
                      ) : (
                        <Link href={`/people?q=${encodeURIComponent(a.name)}`} className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline font-medium truncate block">
                          {a.name}
                        </Link>
                      )}
                      <div className="text-[10px] text-slate-400">
                        {a.role_label || a.role || "\u2014"}
                      </div>
                      {a.mandate_start && (
                        <div className="text-[10px] text-slate-400">
                          Since {shortDate(a.mandate_start)}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
              {currentAdmins.length > 6 && (
                <button type="button" onClick={() => setActiveTab("administrators")} className="w-full text-center text-[10px] text-indigo-500 hover:text-indigo-700 py-1 font-medium">
                  + {currentAdmins.length - 6} more people →
                </button>
              )}
            </div>
          )}
        </div>

        {/* Recent Publications */}
        <div className="rounded-xl border border-slate-100 bg-white p-4">
          <div className="flex items-baseline justify-between mb-3">
            <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <Newspaper className="h-3 w-3" /> Recent Publications
              {(structure?.staatsblad_publications?.length ?? 0) > 0 && (
                <span className="text-slate-300">({structure?.staatsblad_publications?.length})</span>
              )}
            </h3>
            {(structure?.staatsblad_publications?.length ?? 0) > 0 && (
              <button type="button" onClick={() => setActiveTab("publications")} className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
                View all →
              </button>
            )}
          </div>
          {!structure?.staatsblad_publications?.length ? (
            <div className="flex items-center justify-center py-6 text-xs text-slate-300">
              <FileText className="h-4 w-4 mr-2" /> No publications yet
            </div>
          ) : (
            <div className="space-y-1.5">
              {structure.staatsblad_publications.slice(0, 6).map((pub, i) => (
                <div key={`pub-${i}`} className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-50 transition-colors">
                  <div className="h-8 w-8 rounded-full bg-slate-50 flex items-center justify-center shrink-0">
                    <FileText className="h-3.5 w-3.5 text-slate-400" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-xs text-slate-700 truncate">{pub.pub_type || "Publication"}</div>
                    <div className="text-[10px] text-slate-400 flex items-center gap-0.5">
                      <Calendar className="h-2.5 w-2.5" /> {pub.pub_date}
                      {pub.reference && <span className="text-slate-200 ml-1">&middot; #{pub.reference}</span>}
                    </div>
                  </div>
                </div>
              ))}
              {structure.staatsblad_publications.length > 6 && (
                <button type="button" onClick={() => setActiveTab("publications")} className="w-full text-center text-[10px] text-indigo-500 hover:text-indigo-700 py-1 font-medium">
                  + {structure.staatsblad_publications.length - 6} more →
                </button>
              )}
            </div>
          )}
        </div>
        {/* Key Shareholders */}
        <div className="rounded-xl border border-slate-100 bg-white p-4">
          <div className="flex items-baseline justify-between mb-3">
            <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <Briefcase className="h-3 w-3" /> Key Shareholders
              {(structure?.shareholders?.length ?? 0) > 0 && <span className="text-slate-300">({structure?.shareholders?.length})</span>}
            </h3>
            {(structure?.shareholders?.length ?? 0) > 0 && (
              <button type="button" onClick={() => setActiveTab("structure")} className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
                View all →
              </button>
            )}
          </div>
          {!structure?.shareholders?.length ? (
            <div className="flex items-center justify-center py-6 text-xs text-slate-300">
              <Briefcase className="h-4 w-4 mr-2" /> No shareholder data
            </div>
          ) : (
            <div className="space-y-2">
              {structure.shareholders.slice(0, 5).map((sh, i) => {
                const shCbe = cleanCbe(sh.identifier);
                return (
                <div key={`sh-${i}`} className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-50 transition-colors">
                  <div className="h-8 w-8 rounded-full bg-amber-50 flex items-center justify-center text-[10px] font-bold text-amber-600 shrink-0">
                    {(sh.name || "?").slice(0, 2).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    {shCbe ? (
                      <Link href={`/company/${shCbe}`} className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline font-medium truncate block">
                        {sh.name}
                      </Link>
                    ) : (
                      <Link href={`/people?q=${encodeURIComponent(sh.name)}`} className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline font-medium truncate block">
                        {sh.name}
                      </Link>
                    )}
                    <div className="flex items-center gap-2 text-[10px] text-slate-400">
                      <Badge variant="outline" className="text-[9px] px-1.5 py-0 h-4 border-slate-200">
                        {sh.shareholder_type === "entity" || sh.shareholder_type === "Entity" ? "Entity" : "Individual"}
                      </Badge>
                      {sh.fiscal_year && <span className="text-[10px] text-slate-400">Since FY{sh.fiscal_year}</span>}
                    </div>
                  </div>
                  {sh.ownership_pct != null && (
                    <span className="text-xs font-semibold font-mono text-indigo-600 shrink-0">{sh.ownership_pct.toFixed(1)}%</span>
                  )}
                </div>
                );
              })}
              {structure.shareholders.length > 5 && (
                <button type="button" onClick={() => setActiveTab("structure")} className="w-full text-center text-[10px] text-indigo-500 hover:text-indigo-700 py-1 font-medium">
                  + {structure.shareholders.length - 5} more shareholders →
                </button>
              )}
            </div>
          )}
        </div>

        {/* Key Subsidiaries */}
        <div className="rounded-xl border border-slate-100 bg-white p-4">
          <div className="flex items-baseline justify-between mb-3">
            <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <GitBranch className="h-3 w-3" /> Key Subsidiaries
              {(structure?.participating_interests?.length ?? 0) > 0 && <span className="text-slate-300">({structure?.participating_interests?.length})</span>}
            </h3>
            {(structure?.participating_interests?.length ?? 0) > 0 && (
              <button type="button" onClick={() => setActiveTab("structure")} className="text-[10px] text-indigo-500 hover:text-indigo-700 font-medium transition-colors">
                View all →
              </button>
            )}
          </div>
          {!structure?.participating_interests?.length ? (
            <div className="flex items-center justify-center py-6 text-xs text-slate-300">
              <GitBranch className="h-4 w-4 mr-2" /> No subsidiary data
            </div>
          ) : (
            <div className="space-y-2">
              {structure.participating_interests.slice(0, 5).map((sub, i) => {
                const subCbe = cleanCbe(sub.identifier);
                return (
                <div key={`sub-${i}`} className="flex items-center gap-3 p-2 rounded-lg hover:bg-slate-50 transition-colors">
                  <div className="h-8 w-8 rounded-full bg-cyan-50 flex items-center justify-center text-[10px] font-bold text-cyan-600 shrink-0">
                    {(sub.name || "?").slice(0, 2).toUpperCase()}
                  </div>
                  <div className="min-w-0 flex-1">
                    {subCbe ? (
                      <Link href={`/company/${subCbe}`} className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline font-medium truncate block">
                        {sub.name}
                      </Link>
                    ) : (
                      <Link href={`/people?q=${encodeURIComponent(sub.name)}`} className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline font-medium truncate block">
                        {sub.name}
                      </Link>
                    )}
                    <div className="flex items-center gap-2 text-[10px] text-slate-400">
                      {sub.country && <span>{sub.country}</span>}
                      {sub.fiscal_year && <span className="text-[10px] text-slate-400">Since FY{sub.fiscal_year}</span>}
                    </div>
                  </div>
                  {sub.ownership_pct != null && (
                    <span className="text-xs font-semibold font-mono text-indigo-600 shrink-0">{sub.ownership_pct.toFixed(1)}%</span>
                  )}
                </div>
                );
              })}
              {structure.participating_interests.length > 5 && (
                <button type="button" onClick={() => setActiveTab("structure")} className="w-full text-center text-[10px] text-indigo-500 hover:text-indigo-700 py-1 font-medium">
                  + {structure.participating_interests.length - 5} more subsidiaries →
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Financial History Mini Table (last 5 years) */}
      {sorted.length > 1 && (
        <div className="rounded-xl border border-slate-100 bg-white overflow-hidden">
          <div className="px-5 pt-4 pb-2">
            <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider">Financial History</h3>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-t border-slate-50">
                <th className="px-5 py-2 text-left text-slate-400 font-medium">Year</th>
                <th className="px-3 py-2 text-right text-slate-400 font-medium">Revenue</th>
                <th className="px-3 py-2 text-right text-slate-400 font-medium">EBITDA</th>
                <th className="px-3 py-2 text-right text-slate-400 font-medium">Margin</th>
                <th className="px-3 py-2 text-right text-slate-400 font-medium">Net Profit</th>
                <th className="px-3 py-2 text-right text-slate-400 font-medium">FTE</th>
              </tr>
            </thead>
            <tbody>
              {(() => {
                const chronoMini = sorted.slice(0, 5).reverse();
                return chronoMini.map((r, i) => {
                  const prevRow = i > 0 ? chronoMini[i - 1] : null;
                  const isLatest = i === chronoMini.length - 1;
                  return (
                    <tr key={r.fiscal_year} className={isLatest ? "bg-indigo-50/30 font-medium" : "border-t border-slate-50"}>
                      <td className="px-5 py-2 font-mono text-slate-700">{r.fiscal_year}</td>
                      <td className="px-3 py-2 text-right font-mono text-slate-700">
                        {fmtEur(r.revenue)}
                        {renderDelta(r.revenue, prevRow?.revenue ?? null)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-slate-700">
                        {fmtEur(r.ebitda)}
                        {renderDelta(r.ebitda, prevRow?.ebitda ?? null)}
                      </td>
                      <td className={`px-3 py-2 text-right font-mono ${marginColorClass(r.ebitda_margin_pct)}`}>{fmtPct(r.ebitda_margin_pct)}</td>
                      <td className={`px-3 py-2 text-right font-mono ${(r.net_profit ?? 0) < 0 ? "text-rose-400" : "text-slate-700"}`}>
                        {fmtEur(r.net_profit)}
                        {renderDelta(r.net_profit, prevRow?.net_profit ?? null)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-slate-700">
                        {r.fte_total != null ? fmtNumber(r.fte_total) : "\u2014"}
                        {renderDelta(r.fte_total, prevRow?.fte_total ?? null)}
                      </td>
                    </tr>
                  );
                });
              })()}
            </tbody>
          </table>
        </div>
      )}

      {/* Quick navigation links */}
      <div className="flex flex-wrap gap-3 pt-2">
        {sorted.length > 0 && (
          <button
            type="button"
            onClick={() => setActiveTab("pnl")}
            className="text-xs text-indigo-500 hover:text-indigo-700 font-medium flex items-center gap-1 transition-colors"
          >
            P&L details <ChevronRight className="h-3 w-3" />
          </button>
        )}
        {sorted.length > 0 && (
          <button
            type="button"
            onClick={() => setActiveTab("credit")}
            className="text-xs text-indigo-500 hover:text-indigo-700 font-medium flex items-center gap-1 transition-colors"
          >
            Credit analysis <ChevronRight className="h-3 w-3" />
          </button>
        )}
        {currentAdmins.length > 0 && (
          <button
            type="button"
            onClick={() => setActiveTab("administrators")}
            className="text-xs text-indigo-500 hover:text-indigo-700 font-medium flex items-center gap-1 transition-colors"
          >
            {currentAdmins.length} administrator{currentAdmins.length !== 1 ? "s" : ""} <ChevronRight className="h-3 w-3" />
          </button>
        )}
        {(structure?.shareholders?.length ?? 0) > 0 && (
          <button
            type="button"
            onClick={() => setActiveTab("structure")}
            className="text-xs text-indigo-500 hover:text-indigo-700 font-medium flex items-center gap-1 transition-colors"
          >
            Structure <ChevronRight className="h-3 w-3" />
          </button>
        )}
      </div>

      {/* AI Enrichment Section */}
      <div className="rounded-xl border border-indigo-100 bg-indigo-50/30 p-4">
        <div className="flex items-center gap-2 mb-3">
          <Sparkles className="h-4 w-4 text-indigo-500" />
          <h3 className="text-xs font-medium text-slate-600 uppercase tracking-wider">AI Company Summary</h3>
          <span className="inline-flex items-center rounded-full bg-indigo-100 text-indigo-700 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider">Premium</span>
        </div>
        {aiSummary ? (
          <p className="text-sm text-slate-700 leading-relaxed">{aiSummary}</p>
        ) : aiLoading ? (
          <div className="flex items-center gap-2 py-2">
            <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />
            <span className="text-sm text-slate-500">Generating AI summary...</span>
          </div>
        ) : (
          <div className="space-y-2">
            <button
              type="button"
              onClick={onEnrichCompany}
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 transition-colors shadow-sm"
            >
              <Sparkles className="h-4 w-4" />
              Enrich with AI
            </button>
            {aiError && (
              <p className="text-xs text-red-500">{aiError}</p>
            )}
          </div>
        )}
      </div>

      {/* AI Insights: Web & LinkedIn */}
      <div className="rounded-xl border border-slate-200 bg-slate-50/30 p-4">
        <div className="flex items-center gap-2 mb-3">
          <Globe className="h-4 w-4 text-slate-500" />
          <h3 className="text-xs font-medium text-slate-600 uppercase tracking-wider">Web Enrichment</h3>
          <span className="inline-flex items-center rounded-full bg-amber-100 text-amber-700 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider">Premium</span>
        </div>

        <div className="flex flex-wrap gap-2 mb-3">
          {/* AI Insights: Website button */}
          {!websiteScrape && (
            <div className="space-y-1">
              <button
                type="button"
                disabled={websiteScrapeLoading}
                onClick={onScrapeWebsite}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 hover:border-slate-400 transition-colors disabled:opacity-50"
              >
                {websiteScrapeLoading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />
                ) : (
                  <Globe className="h-3.5 w-3.5 text-slate-400" />
                )}
                AI Insights: Website
              </button>
              {websiteError && <p className="text-[10px] text-red-500">{websiteError}</p>}
            </div>
          )}

          {/* AI Insights: LinkedIn button */}
          {!linkedinScrape && (
            <div className="space-y-1">
              <button
                type="button"
                disabled={linkedinScrapeLoading}
                onClick={onScrapeLinkedIn}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 hover:border-slate-400 transition-colors disabled:opacity-50"
              >
                {linkedinScrapeLoading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />
                ) : (
                  <svg className="h-3.5 w-3.5 text-[#0A66C2]" viewBox="0 0 24 24" fill="currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" /></svg>
                )}
                AI Insights: LinkedIn
              </button>
              {linkedinError && <p className="text-[10px] text-red-500">{linkedinError}</p>}
            </div>
          )}
        </div>

        {/* Website AI Insights result */}
        {websiteScrape && (
          <div className="mb-3 rounded-lg border border-slate-200 bg-white p-3 space-y-2">
            <div className="flex items-center gap-2">
              <Globe className="h-3.5 w-3.5 text-slate-400" />
              <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">Website</span>
              {websiteScrape.website_url && (
                <a href={websiteScrape.website_url} target="_blank" rel="noopener noreferrer" className="text-xs text-indigo-500 hover:underline ml-auto flex items-center gap-1">
                  Visit <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>
            {websiteScrape.summary && <p className="text-sm text-slate-700 leading-relaxed">{websiteScrape.summary}</p>}
            {websiteScrape.products && (
              <p className="text-xs text-slate-500"><span className="font-medium text-slate-600">Products:</span> {websiteScrape.products}</p>
            )}
            {websiteScrape.key_people && (
              <p className="text-xs text-slate-500"><span className="font-medium text-slate-600">Key people:</span> {websiteScrape.key_people}</p>
            )}
          </div>
        )}

        {/* LinkedIn AI Insights result */}
        {linkedinScrape && (
          <div className="rounded-lg border border-slate-200 bg-white p-3 space-y-2">
            <div className="flex items-center gap-2">
              <svg className="h-3.5 w-3.5 text-[#0A66C2]" viewBox="0 0 24 24" fill="currentColor"><path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" /></svg>
              <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">LinkedIn</span>
              {linkedinScrape.linkedin_url && (
                <a href={linkedinScrape.linkedin_url} target="_blank" rel="noopener noreferrer" className="text-xs text-indigo-500 hover:underline ml-auto flex items-center gap-1">
                  View profile <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>
            {linkedinScrape.summary && <p className="text-sm text-slate-700 leading-relaxed">{linkedinScrape.summary}</p>}
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {linkedinScrape.industry && (
                <p className="text-xs text-slate-500"><span className="font-medium text-slate-600">Industry:</span> {linkedinScrape.industry}</p>
              )}
              {linkedinScrape.employee_count && (
                <p className="text-xs text-slate-500"><span className="font-medium text-slate-600">Employees:</span> {linkedinScrape.employee_count}</p>
              )}
              {linkedinScrape.specialties && (
                <p className="text-xs text-slate-500"><span className="font-medium text-slate-600">Specialties:</span> {linkedinScrape.specialties}</p>
              )}
            </div>
          </div>
        )}

        {/* Both buttons hidden, no results yet -- show nothing extra */}
        {websiteScrape && linkedinScrape && !websiteScrapeLoading && !linkedinScrapeLoading && (
          <div />
        )}
      </div>
    </div>
  );
}
