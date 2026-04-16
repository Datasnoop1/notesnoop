"use client";

import React from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { fmtEur, fmtPct, fmtNumber } from "@/lib/format";
import {
  ChevronRight,
  Users,
  Briefcase,
  GitBranch,
  FileText,
  BarChart3,
  DollarSign,
  TrendingUp,
  Percent,
  Calendar,
  UserCheck,
  Newspaper,
  Shield,
  Scale,
  Landmark,
} from "lucide-react";
import type {
  CompanyDetail,
  FinancialsData,
  StructureData,
} from "../types";
import { renderDelta, cleanCbe } from "../helpers";

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
  let equityRatio: number | null = null;
  let interestCoverage: number | null = null;
  if (latest) {
    const grossDebt = (latest.lt_financial_debt ?? 0) + (latest.st_financial_debt ?? 0);
    const netDebt = grossDebt - (latest.cash ?? 0) - (latest.current_investments ?? 0);
    netDebtEbitda = latest.ebitda && latest.ebitda !== 0 ? netDebt / latest.ebitda : null;
    equityRatio = latest.total_assets && latest.total_assets !== 0 && latest.equity != null
      ? (latest.equity / latest.total_assets) * 100
      : null;
    interestCoverage = latest.financial_charges && latest.financial_charges !== 0 && latest.ebitda != null
      ? latest.ebitda / Math.abs(latest.financial_charges)
      : null;
  }

  const revenueYoy = yoyChange(latest?.revenue ?? null, prev?.revenue ?? null);
  const ebitdaYoy = yoyChange(latest?.ebitda ?? null, prev?.ebitda ?? null);
  const fteYoy = yoyChange(latest?.fte_total ?? null, prev?.fte_total ?? null);

  return (
    <div className="space-y-6">
      {/* Key Financials — full-width KPI cards + Financial History (no gap) */}
      {latest && (
        <div className="rounded-xl border border-slate-100 bg-white overflow-hidden">
          {/* Header */}
          <div className="px-5 pt-4 pb-3 flex items-baseline justify-between">
            <h3 className="text-[10px] font-medium text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <BarChart3 className="h-3 w-3" /> Key Financials
              {latest.fiscal_year && <span className="text-slate-300 font-mono">FY{latest.fiscal_year}</span>}
            </h3>
            {/* Link removed — P&L has its own tab */}
          </div>
          {/* KPI cards row */}
          <div className="px-5 pb-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-3">
            {/* Revenue */}
            <div className="rounded-lg bg-slate-50 px-3 py-2.5">
              <div className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
                <DollarSign className="h-3 w-3" /> Revenue
              </div>
              <div className="text-sm font-semibold text-slate-900 font-mono">{fmtEur(latest.revenue)}</div>
              {changeArrow(revenueYoy) && <div className="mt-0.5">{changeArrow(revenueYoy)}</div>}
            </div>
            {/* EBITDA */}
            <div className="rounded-lg bg-slate-50 px-3 py-2.5">
              <div className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
                <TrendingUp className="h-3 w-3" /> EBITDA
              </div>
              <div className="text-sm font-semibold text-slate-900 font-mono">{fmtEur(latest.ebitda)}</div>
              {changeArrow(ebitdaYoy) && <div className="mt-0.5">{changeArrow(ebitdaYoy)}</div>}
            </div>
            {/* Margin */}
            <div className="rounded-lg bg-slate-50 px-3 py-2.5">
              <div className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
                <Percent className="h-3 w-3" /> Margin
              </div>
              <div className={`text-sm font-semibold font-mono ${marginColorClass(latest.ebitda_margin_pct)}`}>{fmtPct(latest.ebitda_margin_pct)}</div>
            </div>
            {/* Employees */}
            <div className="rounded-lg bg-slate-50 px-3 py-2.5">
              <div className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
                <Users className="h-3 w-3" /> Employees
              </div>
              <div className="text-sm font-semibold text-slate-900 font-mono">{latest.fte_total != null ? fmtNumber(latest.fte_total) : "\u2014"}</div>
              {changeArrow(fteYoy) && <div className="mt-0.5">{changeArrow(fteYoy)}</div>}
            </div>
            {/* Net Debt / EBITDA */}
            <div className="rounded-lg bg-slate-50 px-3 py-2.5">
              <div className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
                <Scale className="h-3 w-3" /> Leverage
              </div>
              <div className={`text-sm font-semibold font-mono ${netDebtEbitda != null && isFinite(netDebtEbitda) ? (netDebtEbitda < 3 ? "text-emerald-600" : netDebtEbitda <= 5 ? "text-amber-600" : "text-rose-400") : "text-slate-900"}`}>
                {netDebtEbitda != null && isFinite(netDebtEbitda) ? `${netDebtEbitda.toFixed(1)}x` : "\u2014"}
              </div>
              <div className="text-[9px] text-slate-400 mt-0.5">Net Debt / EBITDA</div>
            </div>
            {/* Equity Ratio */}
            <div className="rounded-lg bg-slate-50 px-3 py-2.5">
              <div className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
                <Shield className="h-3 w-3" /> Equity Ratio
              </div>
              <div className={`text-sm font-semibold font-mono ${equityRatio != null ? (equityRatio >= 30 ? "text-emerald-600" : equityRatio >= 15 ? "text-amber-600" : "text-rose-400") : "text-slate-900"}`}>
                {equityRatio != null ? `${equityRatio.toFixed(1)}%` : "\u2014"}
              </div>
              <div className="text-[9px] text-slate-400 mt-0.5">Equity / Assets</div>
            </div>
            {/* Interest Coverage */}
            <div className="rounded-lg bg-slate-50 px-3 py-2.5">
              <div className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
                <Landmark className="h-3 w-3" /> Int. Coverage
              </div>
              <div className={`text-sm font-semibold font-mono ${interestCoverage != null ? (interestCoverage >= 3 ? "text-emerald-600" : interestCoverage >= 1.5 ? "text-amber-600" : "text-rose-400") : "text-slate-900"}`}>
                {interestCoverage != null && isFinite(interestCoverage) ? `${interestCoverage.toFixed(1)}x` : "\u2014"}
              </div>
              <div className="text-[9px] text-slate-400 mt-0.5">EBITDA / Int. Exp</div>
            </div>
          </div>

          {/* Financial History table — directly inside same card, no gap */}
          {sorted.length > 1 && (
            <>
              <div className="px-5 pt-3 pb-2 border-t border-slate-100">
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
                    const recentFirst = sorted.slice(0, 5);
                    return recentFirst.map((r, i) => {
                      const prevRow = i < recentFirst.length - 1 ? recentFirst[i + 1] : null;
                      const isLatest = i === 0;
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
            </>
          )}
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

      {/* Old AI enrichment and web enrichment sections removed —
           AI Insights now available via the Sparkles button in the header */}
    </div>
  );
}
