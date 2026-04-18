"use client";

import React from "react";
import { useTranslation } from "@/components/language-provider";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import ExportButtons from "@/components/export-buttons";
import { fmtEur } from "@/lib/format";
import { renderDelta, renderDeltaHeaders } from "../helpers";
import type { FinancialsData } from "../types";
import {
  Download,
  Loader2,
  CheckCircle2,
  XCircle,
  DollarSign,
  Percent,
  BarChart3,
  Activity,
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { getCompanyFinancials, loadCompanyNBB } from "@/lib/api";
import { PnlWaterfall } from "./pnl-waterfall";

/* ---------- Chart tooltip (local) ---------- */

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-white p-3 shadow-md">
      <p className="mb-1 text-xs font-semibold text-slate-700">FY {label}</p>
      {payload.map((entry) => (
        <p key={entry.name} className="text-xs" style={{ color: entry.color }}>
          {entry.name}: {fmtEur(entry.value)}
        </p>
      ))}
    </div>
  );
}

/* ---------- Props ---------- */

interface PnlTabProps {
  financials: FinancialsData | null;
  nbbLoading: boolean;
  nbbResult: "success" | "error" | "no-data" | "pdf-only" | null;
  setNbbLoading: (v: boolean) => void;
  setNbbResult: (v: "success" | "error" | "no-data" | "pdf-only" | null) => void;
  setFinancials: (v: FinancialsData) => void;
  cbe: string;
  companyName: string | null;
  collapsedSections: Record<string, boolean>;
  toggleSection: (key: string) => void;
  chartData: Array<{ fy: string; Revenue: number | null; EBITDA: number | null }>;
}

/* ---------- Component ---------- */

export function PnlTab({
  financials,
  nbbLoading,
  nbbResult,
  setNbbLoading,
  setNbbResult,
  setFinancials,
  cbe,
  companyName,
  collapsedSections,
  toggleSection,
  chartData,
}: PnlTabProps) {
  const { t } = useTranslation();

  if (!financials || financials.summary.length === 0) {
    const isPdfOnly = financials?.pdf_only === true || nbbResult === "pdf-only";
    return (
      <div className="py-8 text-center">
        {nbbLoading ? (
          <div className="flex flex-col items-center gap-2">
            <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
            <p className="text-sm text-slate-500 animate-pulse">
              {t("company.pnl.loadingNbb")}
            </p>
          </div>
        ) : isPdfOnly ? (
          <div className="mx-auto max-w-xl rounded-lg border border-amber-200 bg-amber-50 p-4 text-left">
            <p className="text-sm font-semibold text-amber-800 mb-1">
              {t("company.pnl.pdfOnlyTitle")}
            </p>
            <p className="text-xs text-amber-700 mb-2">
              {t("company.pnl.pdfOnlyBody")}
            </p>
            <a
              href={`https://consult.cbso.nbb.be/consult-enterprise/${cbe}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs font-medium text-amber-700 underline hover:text-amber-900"
            >
              {t("company.pnl.pdfOnlyLink")} {"\u2192"}
            </a>
          </div>
        ) : (
          <>
            <p className="text-sm text-slate-500 mb-4">
              {nbbResult === "no-data"
                ? t("company.pnl.noFilings")
                : t("company.pnl.noData")}
            </p>
            <Button
              variant="outline"
              disabled={nbbLoading}
              onClick={async () => {
                setNbbLoading(true);
                setNbbResult(null);
                try {
                  const data = await loadCompanyNBB(cbe);
                  if (data.rubrics_loaded > 0) {
                    setNbbResult("success");
                    getCompanyFinancials(cbe).then(f => setFinancials(f as unknown as FinancialsData)).catch(() => setNbbResult("error"));
                  } else if (data.pdf_only) {
                    setNbbResult("pdf-only");
                  } else {
                    setNbbResult("no-data");
                  }
                } catch {
                  setNbbResult("error");
                } finally {
                  setNbbLoading(false);
                }
              }}
              className={`text-indigo-600 border-indigo-300 hover:bg-indigo-50 ${nbbLoading ? "opacity-70 cursor-not-allowed" : ""}`}
            >
              <Download className="w-4 h-4 mr-2" />
              {nbbResult === "no-data" ? t("company.pnl.retryNbb") : t("company.pnl.loadNbb")}
            </Button>
            {nbbResult === "success" && (
              <div className="mt-3 flex items-center justify-center gap-1.5 text-xs text-emerald-600">
                <CheckCircle2 className="w-4 h-4" />
                {t("company.pnl.dataLoaded")}
              </div>
            )}
            {nbbResult === "error" && (
              <div className="mt-3 flex items-center justify-center gap-1.5 text-xs text-rose-400">
                <XCircle className="w-4 h-4" />
                {t("company.pnl.loadFailed")}
              </div>
            )}
          </>
        )}
      </div>
    );
  }

  const sorted = [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year);
  const chronological = [...sorted].reverse();

  // Derive P&L line items per year
  const pnlData = sorted.map((row) => {
    const revenue = row.revenue;
    const grossMargin = row.gross_margin;
    const costOfSales = revenue != null && grossMargin != null ? -(revenue - grossMargin) : null;
    const personnel = row.personnel_costs != null ? -Math.abs(row.personnel_costs) : null;
    const da = row.da != null ? -Math.abs(row.da) : null;
    const ebit = row.ebit;
    const otherOpCosts = grossMargin != null && ebit != null
      ? -(grossMargin - (ebit) - Math.abs(row.personnel_costs ?? 0) - Math.abs(row.da ?? 0))
      : null;
    const finCharges = row.financial_charges != null ? -Math.abs(row.financial_charges) : null;
    const pbt = ebit != null && row.financial_charges != null ? ebit - Math.abs(row.financial_charges) : null;
    const netProfit = row.net_profit;
    const tax = pbt != null && netProfit != null ? -(pbt - netProfit) : null;
    return {
      fiscal_year: row.fiscal_year,
      revenue,
      costOfSales,
      grossMargin,
      personnel,
      da,
      otherOpCosts: otherOpCosts != null && Math.abs(otherOpCosts) > 0.5 ? otherOpCosts : null,
      ebit,
      finCharges,
      pbt,
      tax,
      netProfit,
      ebitda: row.ebitda,
      ebitdaMarginPct: row.ebitda_margin_pct,
    };
  });

  // Helper: format accounting cell
  // isCost: show in parentheses but normal color (costs are expected to be negative)
  // isKeyMetric: show rose only if negative (EBITDA, EBIT, Net Profit)
  const fmtAcct = (v: number | null, isCost = false, isKeyMetric = false) => {
    if (v == null) return <span className="text-slate-300">{"\u2014"}</span>;
    if (isCost && v < 0) {
      return <span className="text-slate-500">({fmtEur(Math.abs(v))})</span>;
    }
    if (isKeyMetric && v < 0) {
      return <span className="text-rose-400">({fmtEur(Math.abs(v))})</span>;
    }
    if (v < 0) {
      return <span className="text-slate-500">({fmtEur(Math.abs(v))})</span>;
    }
    return <>{fmtEur(v)}</>;
  };

  type PnlLine = {
    label: string;
    key: keyof (typeof pnlData)[0];
    isCost?: boolean;
    isKeyMetric?: boolean;
    bold?: boolean;
    topBorder?: boolean;
    doubleBorder?: boolean;
    section?: string;
    indent?: boolean;
    isPct?: boolean;
    group?: string;
  };

  const chronologicalPnl = [...pnlData].reverse();

  const lines: PnlLine[] = [
    { label: t("company.pnl.revenue"), key: "revenue", section: t("company.pnl.sectionRevenue") },
    { label: t("company.pnl.costOfSales"), key: "costOfSales", isCost: true, indent: true },
    { label: t("company.pnl.grossProfit"), key: "grossMargin", bold: true, topBorder: true },
    { label: t("company.pnl.personnelCosts"), key: "personnel", isCost: true, section: t("company.pnl.sectionOpCosts"), indent: true, group: "pnl_opex" },
    { label: t("company.pnl.da"), key: "da", isCost: true, indent: true, group: "pnl_opex" },
    { label: t("company.pnl.otherOpCosts"), key: "otherOpCosts", isCost: true, indent: true, group: "pnl_opex" },
    { label: t("company.pnl.ebitOp"), key: "ebit", bold: true, topBorder: true, isKeyMetric: true },
    { label: t("company.pnl.financialCharges"), key: "finCharges", isCost: true, section: t("company.pnl.sectionFinancial"), indent: true },
    { label: t("company.pnl.pbt"), key: "pbt", bold: true, topBorder: true, isKeyMetric: true },
    { label: t("company.pnl.tax"), key: "tax", isCost: true, indent: true },
    { label: t("company.pnl.netProfit"), key: "netProfit", bold: true, doubleBorder: true, isKeyMetric: true },
    { label: t("company.pnl.ebitda"), key: "ebitda", bold: true, section: t("company.pnl.sectionEbitda"), topBorder: true, isKeyMetric: true },
    { label: t("company.pnl.ebitdaMargin"), key: "ebitdaMarginPct", isPct: true },
  ];

  let lastSection = "";

  function exportPnlCsv() {
    const headers = ["Line Item", ...sorted.map(r => `FY${r.fiscal_year}`)];
    const csvLines = lines.map(line => {
      const cells = pnlData.map(r => {
        const v = r[line.key];
        if (v == null) return "";
        if (line.isPct) return `${(v as number).toFixed(1)}%`;
        return String(v);
      });
      return [line.label, ...cells].join(",");
    });
    const blob = new Blob([headers.join(",") + "\n" + csvLines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${companyName || cbe}_pnl.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Core metrics summary
  const latestPnl = pnlData.find((_, i) => i === 0); // newest
  const prevPnl = pnlData.length > 1 ? pnlData[1] : null;

  const revGrowth = latestPnl?.revenue != null && prevPnl?.revenue != null && prevPnl.revenue !== 0
    ? ((latestPnl.revenue - prevPnl.revenue) / Math.abs(prevPnl.revenue)) * 100 : null;
  const grossMarginPct = latestPnl?.revenue != null && latestPnl?.grossMargin != null && latestPnl.revenue !== 0
    ? (latestPnl.grossMargin / latestPnl.revenue) * 100 : null;
  const ebitdaPct = latestPnl?.ebitdaMarginPct ?? null;
  const ebitdaGrowth = latestPnl?.ebitda != null && prevPnl?.ebitda != null && prevPnl.ebitda !== 0
    ? ((latestPnl.ebitda - prevPnl.ebitda) / Math.abs(prevPnl.ebitda)) * 100 : null;
  const ebitPct = latestPnl?.revenue != null && latestPnl?.ebit != null && latestPnl.revenue !== 0
    ? (latestPnl.ebit / latestPnl.revenue) * 100 : null;
  const ebitGrowth = latestPnl?.ebit != null && prevPnl?.ebit != null && prevPnl.ebit !== 0
    ? ((latestPnl.ebit - prevPnl.ebit) / Math.abs(prevPnl.ebit)) * 100 : null;

  const growthPill = (v: number | null) => {
    if (v == null) return null;
    const color = v > 2 ? "text-emerald-600" : v < -2 ? "text-rose-400" : "text-slate-500";
    const arrow = v > 0.5 ? "\u2191" : v < -0.5 ? "\u2193" : "\u2192";
    return <span className={`text-[10px] font-medium ${color}`}>{arrow} {Math.abs(v).toFixed(1)}%</span>;
  };

  const marginPill = (v: number | null) => {
    if (v == null) return <span className="text-slate-300 text-xs font-mono">\u2014</span>;
    const color = v >= 15 ? "text-emerald-600" : v >= 5 ? "text-amber-600" : "text-rose-400";
    return <span className={`text-xs font-mono font-semibold ${color}`}>{v.toFixed(1)}%</span>;
  };

  return (
    <div className="space-y-4">
      {/* -- Core Metrics Summary -- */}
      {latestPnl && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-2">
          {[
            { label: t("company.pnl.revenue"), value: fmtEur(latestPnl.revenue), sub: growthPill(revGrowth), icon: <DollarSign className="h-3 w-3" /> },
            { label: t("company.pnl.grossMargin"), value: marginPill(grossMarginPct), sub: null, icon: <Percent className="h-3 w-3" /> },
            { label: t("company.pnl.ebitda"), value: fmtEur(latestPnl.ebitda), sub: growthPill(ebitdaGrowth), icon: <BarChart3 className="h-3 w-3" /> },
            { label: t("company.pnl.ebitdaPct"), value: marginPill(ebitdaPct), sub: null, icon: <Percent className="h-3 w-3" /> },
            { label: t("company.ebit"), value: fmtEur(latestPnl.ebit), sub: growthPill(ebitGrowth), icon: <Activity className="h-3 w-3" /> },
            { label: t("company.pnl.ebitPct"), value: marginPill(ebitPct), sub: null, icon: <Percent className="h-3 w-3" /> },
            { label: t("company.pnl.netProfit"), value: fmtEur(latestPnl.netProfit), sub: null, icon: <DollarSign className="h-3 w-3" /> },
          ].map((m, i) => (
            <div key={i} className="rounded-lg border border-slate-100 bg-white p-2.5 text-center">
              <div className="flex items-center justify-center gap-1 text-[10px] text-slate-400 uppercase tracking-wider mb-1">
                {m.icon} {m.label}
              </div>
              <div className="text-sm font-semibold text-slate-800 font-mono">{m.value}</div>
              {m.sub && <div className="mt-0.5">{m.sub}</div>}
            </div>
          ))}
        </div>
      )}

      {/* P&L waterfall — under the KPI cards, expanded by default (per
          operator), year picker so they can switch fiscal year in-place. */}
      {financials?.rubric_data && pnlData.length > 0 && (
        <PnlWaterfall
          rubrics={financials.rubric_data as Record<string, Record<string, number | null>>}
          fiscalYears={pnlData.map((p) => p.fiscal_year).filter((y): y is number => typeof y === "number")}
        />
      )}

      {/* -- Income Statement -- */}
      <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2">
          {t("company.pnl.title")}
        </h3>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => toggleSection("pnl_opex")}
            className={`text-[11px] px-2.5 py-1.5 md:py-0.5 rounded border transition-colors ${collapsedSections.pnl_opex ? "bg-indigo-50 border-indigo-200 text-indigo-600" : "bg-white border-slate-200 text-slate-500 hover:border-slate-300"}`}
          >
            {collapsedSections.pnl_opex ? `\u25b8 ${t("company.pnl.opexGrouped")}` : `\u25be ${t("company.pnl.opexExpanded")}`}
          </button>
          <ExportButtons
            onExportCSV={exportPnlCsv}
            onPrint={() => window.print()}
          />
        </div>
      </div>
      <div className="rounded-lg border overflow-x-auto bg-white">
        <table className="w-full min-w-[560px] md:min-w-[900px]">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="sticky left-0 z-10 bg-slate-50 px-2 md:px-4 py-2 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[110px] md:w-auto md:min-w-[240px] shadow-[1px_0_0_rgba(226,232,240,1)]">{t("company.pnl.lineItem")}</th>
              {renderDeltaHeaders(chronological.map(r => r.fiscal_year))}
            </tr>
          </thead>
          <tbody>
            {(() => {
              // Track whether we've already rendered the collapsed-opex
              // summary row so we only show it once between Gross profit
              // and EBIT, not before every hidden line.
              let opexSummaryShown = false;
              return lines.map((line) => {
              // When the opex group is collapsed, replace its first line
              // with a single summary row that has a click-to-expand toggle.
              const opexCollapsed = line.group === "pnl_opex" && collapsedSections.pnl_opex;
              if (opexCollapsed && opexSummaryShown) return null;
              if (opexCollapsed && !opexSummaryShown) {
                opexSummaryShown = true;
                return (
                  <tr key="pnl-opex-summary" className="border-t border-slate-200">
                    <td className="sticky left-0 z-[5] bg-white px-2 md:px-4 py-1 text-[11px] md:text-xs shadow-[1px_0_0_rgba(226,232,240,1)] text-slate-600">
                      <button
                        type="button"
                        onClick={() => toggleSection("pnl_opex")}
                        className="inline-flex items-center gap-1 hover:text-indigo-600 transition-colors"
                      >
                        <span className="text-[10px]">▸</span>
                        <span className="font-medium">{t("company.pnl.sectionOpCosts") || "Operating costs"}</span>
                        <span className="text-[10px] text-slate-400">({t("company.pnl.opexExpanded") || "click to expand"})</span>
                      </button>
                    </td>
                    {chronologicalPnl.map((r, colIdx) => {
                      const prevRow = colIdx > 0 ? chronologicalPnl[colIdx - 1] : null;
                      const sum = (n: number | null | undefined) => typeof n === "number" ? n : 0;
                      const opex = sum(r.personnel) + sum(r.da) + sum(r.otherOpCosts);
                      const prevOpex = prevRow ? sum(prevRow.personnel) + sum(prevRow.da) + sum(prevRow.otherOpCosts) : null;
                      return (
                        <React.Fragment key={`opex-sum-${r.fiscal_year}`}>
                          {colIdx > 0 && (
                            <td className="px-0.5 md:px-1 py-1 text-center align-top w-[32px] md:w-[70px]">
                              {renderDelta(opex, prevOpex)}
                            </td>
                          )}
                          <td className="px-1.5 md:px-3 py-1 text-right text-[11px] md:text-xs font-mono text-slate-600">
                            {fmtAcct(opex, true, false)}
                          </td>
                        </React.Fragment>
                      );
                    })}
                  </tr>
                );
              }

              const showSection = line.section && line.section !== lastSection;
              if (line.section) lastSection = line.section;
              return (
                <React.Fragment key={line.key}>
                  {showSection && (
                    <tr>
                      <td colSpan={chronological.length * 2} className="sticky left-0 bg-white px-4 pt-3 pb-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest">{line.section}</span>
                      </td>
                    </tr>
                  )}
                  <tr className={`${line.topBorder ? "border-t border-slate-200" : ""} ${line.doubleBorder ? "border-t-2 border-slate-400" : ""}`}>
                    <td className={`sticky left-0 z-[5] bg-white px-2 md:px-4 py-1 text-[11px] md:text-xs whitespace-normal break-words w-[110px] md:w-auto shadow-[1px_0_0_rgba(226,232,240,1)] ${line.bold ? "font-bold text-slate-800" : "text-slate-600"} ${line.indent ? "pl-4 md:pl-8" : ""}`}>
                      {line.label}
                    </td>
                    {chronologicalPnl.map((r, colIdx) => {
                      const prevRow = colIdx > 0 ? chronologicalPnl[colIdx - 1] : null;
                      const currentVal = r[line.key] as number | null;
                      const prevVal = prevRow ? (prevRow[line.key] as number | null) : null;
                      return (
                        <React.Fragment key={`cell-${r.fiscal_year}-${line.key}`}>
                          {colIdx > 0 && (
                            <td className="px-0.5 md:px-1 py-1 text-center align-top w-[32px] md:w-[70px]">
                              {!line.isPct ? renderDelta(currentVal, prevVal) : null}
                            </td>
                          )}
                          <td className={`px-1.5 md:px-3 py-1 text-right text-[11px] md:text-xs font-mono ${line.bold ? "font-bold" : ""}`}>
                            {line.isPct
                              ? (currentVal != null
                                  ? <span className={`${(currentVal as number) >= 15 ? "text-emerald-600" : (currentVal as number) >= 5 ? "text-amber-600" : "text-rose-400"}`}>{(currentVal as number).toFixed(1)}%</span>
                                  : <span className="text-slate-300">{"\u2014"}</span>)
                              : fmtAcct(currentVal, line.isCost, line.isKeyMetric)}
                          </td>
                        </React.Fragment>
                      );
                    })}
                  </tr>
                </React.Fragment>
              );
            });
            })()}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-[11px] text-slate-400 italic">
        {t("company.pnl.footnote")}
      </p>
      </div>

      {/* Revenue & EBITDA Chart */}
      {chartData.length >= 2 && (
        <Card className="mt-4">
          <CardContent className="pt-3 pb-3">
            <h3 className="mb-3 text-xs font-semibold text-slate-700">
              {t("company.pnl.chartTitle")}
            </h3>
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="fy" tick={{ fontSize: 12, fill: "#64748b" }} />
                <YAxis tick={{ fontSize: 12, fill: "#64748b" }} tickFormatter={(v: number) => fmtEur(v)} />
                <Tooltip content={<ChartTooltip />} />
                <Legend wrapperStyle={{ fontSize: "12px" }} />
                <Line type="monotone" dataKey="Revenue" stroke="#4f46e5" strokeWidth={2} dot={{ r: 4, fill: "#4f46e5" }} />
                <Line type="monotone" dataKey="EBITDA" stroke="#06b6d4" strokeWidth={2} dot={{ r: 4, fill: "#06b6d4" }} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
