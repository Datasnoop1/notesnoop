"use client";

import React from "react";
import { useTranslation } from "@/components/language-provider";
import ExportButtons from "@/components/export-buttons";
import { fmtEur } from "@/lib/format";
import { renderDelta, renderDeltaHeaders } from "../helpers";
import type { FinancialsData } from "../types";
import { PdfOnlyBanner } from "./pdf-only-banner";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

/* ---------- Props ---------- */

interface BalanceSheetTabProps {
  financials: FinancialsData | null;
  cbe: string;
  companyName: string | null;
  collapsedSections: Record<string, boolean>;
  toggleSection: (key: string) => void;
}

/* ---------- Component ---------- */

export function BalanceSheetTab({
  financials,
  cbe,
  companyName,
  collapsedSections,
  toggleSection,
}: BalanceSheetTabProps) {
  const { t } = useTranslation();

  if (!financials || financials.summary.length === 0) {
    if (financials?.pdf_only) {
      return (
        <div className="py-8">
          <PdfOnlyBanner cbe={cbe} />
        </div>
      );
    }
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        {t("company.bs.noData")}
      </p>
    );
  }

  const sorted = [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year);
  const chronological = [...sorted].reverse();

  // Helper: format value, red if negative
  const fmtCell = (v: number | null) => {
    if (v == null) return <span className="text-slate-300">{"\u2014"}</span>;
    const formatted = fmtEur(v);
    return v < 0 ? <span className="text-rose-400">{formatted}</span> : <>{formatted}</>;
  };

  // Helper: pull a rubric value for a given fiscal year out of rubric_data
  const rubricFor = (code: string, fy: number): number | null => {
    const v = financials.rubric_data?.[code]?.[String(fy)];
    return v == null ? null : v;
  };

  // Build derived rows per year
  const bsRows = sorted.map((row) => {
    const fixedAssets = row.fixed_assets ?? null;
    const intangibleAssets = rubricFor("21", row.fiscal_year);
    const tangibleAssets = rubricFor("22", row.fiscal_year);
    const financialAssets = rubricFor("28", row.fiscal_year);
    const totalAssets = row.total_assets ?? null;
    const currentAssets = totalAssets != null && fixedAssets != null ? totalAssets - fixedAssets : null;
    const inventories = row.inventories ?? null;
    const tradeReceivables = row.trade_receivables ?? null;
    const cash = row.cash ?? null;
    const currentInvestments = row.current_investments ?? null;
    const otherCurrentAssets = currentAssets != null
      ? currentAssets - (inventories ?? 0) - (tradeReceivables ?? 0) - (cash ?? 0) - (currentInvestments ?? 0)
      : null;

    const equity = row.equity ?? null;
    const ltDebt = row.lt_debt ?? null;
    const ltFinDebt = row.lt_financial_debt ?? null;
    const totalLE = totalAssets; // must balance
    const totalNonCurrentLiab = ltDebt;
    const totalCurrentLiab = totalLE != null && equity != null && ltDebt != null
      ? totalLE - equity - ltDebt
      : null;
    const stFinDebt = row.st_financial_debt ?? null;
    const tradePayables = row.trade_payables ?? null;
    const otherCurrentLiab = totalCurrentLiab != null
      ? totalCurrentLiab - (stFinDebt ?? 0) - (tradePayables ?? 0)
      : null;

    return {
      fiscal_year: row.fiscal_year,
      fixedAssets,
      intangibleAssets,
      tangibleAssets,
      financialAssets,
      totalNonCurrentAssets: fixedAssets,
      currentAssets,
      inventories,
      tradeReceivables,
      cash,
      currentInvestments,
      otherCurrentAssets: otherCurrentAssets != null && Math.abs(otherCurrentAssets) > 0.5 ? otherCurrentAssets : null,
      totalCurrentAssets: currentAssets,
      totalAssets,
      equity,
      ltDebt,
      ltFinDebt,
      totalNonCurrentLiab,
      tradePayables,
      stFinDebt,
      otherCurrentLiab: otherCurrentLiab != null && Math.abs(otherCurrentLiab) > 0.5 ? otherCurrentLiab : null,
      totalCurrentLiab,
      totalLE: totalAssets,
    };
  });
  const chronologicalBs = [...bsRows].reverse();

  type BSLine = {
    label: string;
    key: keyof (typeof bsRows)[0];
    bold?: boolean;
    indent?: boolean;
    topBorder?: boolean;
    doubleBorder?: boolean;
    section?: string;
    subIndent?: boolean;
    group?: string;
  };

  const lines: BSLine[] = [
    // ASSETS
    { label: t("company.bs.intangibleAssets"), key: "intangibleAssets", indent: true, section: t("company.bs.sectionNonCurrentAssets"), group: "bs_fa" },
    { label: t("company.bs.tangibleAssets"), key: "tangibleAssets", indent: true, group: "bs_fa" },
    { label: t("company.bs.financialAssets"), key: "financialAssets", indent: true, group: "bs_fa" },
    { label: t("company.bs.totalNonCurrentAssets"), key: "totalNonCurrentAssets", bold: true, topBorder: true, section: t("company.bs.sectionNonCurrentAssets") },
    { label: t("company.bs.inventories"), key: "inventories", indent: true, section: t("company.bs.sectionCurrentAssets"), group: "bs_ca" },
    { label: t("company.bs.tradeReceivables"), key: "tradeReceivables", indent: true, group: "bs_ca" },
    { label: t("company.bs.cashEquivalents"), key: "cash", indent: true, group: "bs_ca" },
    { label: t("company.bs.stInvestments"), key: "currentInvestments", indent: true, group: "bs_ca" },
    { label: t("company.bs.otherCurrentAssets"), key: "otherCurrentAssets", indent: true, group: "bs_ca" },
    { label: t("company.bs.totalCurrentAssets"), key: "totalCurrentAssets", bold: true, topBorder: true },
    { label: t("company.bs.totalAssets"), key: "totalAssets", bold: true, doubleBorder: true },
    // EQUITY & LIABILITIES
    { label: t("company.bs.totalEquity"), key: "equity", bold: true, section: t("company.bs.sectionEquity") },
    { label: t("company.bs.ltDebt"), key: "ltDebt", indent: true, section: t("company.bs.sectionNonCurrentLiab") },
    { label: t("company.bs.ltFinDebt"), key: "ltFinDebt", subIndent: true },
    { label: t("company.bs.totalNonCurrentLiab"), key: "totalNonCurrentLiab", bold: true, topBorder: true },
    { label: t("company.bs.tradePayables"), key: "tradePayables", indent: true, section: t("company.bs.sectionCurrentLiab"), group: "bs_cl" },
    { label: t("company.bs.stFinDebt"), key: "stFinDebt", indent: true, group: "bs_cl" },
    { label: t("company.bs.otherCurrentLiab"), key: "otherCurrentLiab", indent: true, group: "bs_cl" },
    { label: t("company.bs.totalCurrentLiab"), key: "totalCurrentLiab", bold: true, topBorder: true },
    { label: t("company.bs.totalEqLiab"), key: "totalLE", bold: true, doubleBorder: true },
  ];

  let lastSection = "";

  function exportBsCsv() {
    const headers = [t("company.bs.lineItem"), ...sorted.map(r => `FY${r.fiscal_year}`)];
    const csvLines = lines.map(line => {
      const cells = bsRows.map(r => {
        const v = r[line.key];
        if (v == null) return "";
        return String(v);
      });
      return [line.label, ...cells].join(",");
    });
    const blob = new Blob([headers.join(",") + "\n" + csvLines.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${companyName || cbe}_balance_sheet.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Latest year breakdown for the asset/financing bridge chart.
  // Single stackId, distinct keys per side — each row only has values for
  // its own side, the other side's keys are zero, so recharts stacks them
  // cleanly. Residual on each side absorbs any data-quality gap, so both
  // bars always sum to totalAssets (balance-sheet identity).
  const latest = bsRows[0];
  const bridgeData = (() => {
    if (!latest || !latest.totalAssets) return null;
    const target = latest.totalAssets;

    // Assets
    const fa = Math.max(latest.totalNonCurrentAssets ?? 0, 0);
    const inv = Math.max(latest.inventories ?? 0, 0);
    const rec = Math.max(latest.tradeReceivables ?? 0, 0);
    const cash = Math.max((latest.cash ?? 0) + (latest.currentInvestments ?? 0), 0);
    const otherA = Math.max(target - fa - inv - rec - cash, 0);

    // Equity + Liabilities. Negative equity clamped to 0 in the bar; shown
    // separately as a note below the chart.
    const eq = Math.max(latest.equity ?? 0, 0);
    const ltd = Math.max(latest.ltDebt ?? 0, 0);
    const std = Math.max(latest.stFinDebt ?? 0, 0);
    const tp = Math.max(latest.tradePayables ?? 0, 0);
    const otherL = Math.max(target - eq - ltd - std - tp, 0);

    return [
      {
        side: "Assets",
        fixedAssets: fa,
        inventories: inv,
        receivables: rec,
        cash: cash,
        otherAssets: otherA,
        // Liability keys absent on this row
        equity: 0, ltDebt: 0, stDebt: 0, tradePay: 0, otherLiab: 0,
      },
      {
        side: "Equity + Liabilities",
        fixedAssets: 0, inventories: 0, receivables: 0, cash: 0, otherAssets: 0,
        equity: eq,
        ltDebt: ltd,
        stDebt: std,
        tradePay: tp,
        otherLiab: otherL,
      },
    ];
  })();
  const negEquity = latest?.equity != null && latest.equity < 0 ? latest.equity : null;

  type BridgeKey = "fixedAssets" | "inventories" | "receivables" | "cash" | "otherAssets"
    | "equity" | "ltDebt" | "stDebt" | "tradePay" | "otherLiab";
  const BRIDGE_BARS: Array<{ key: BridgeKey; label: string; color: string }> = [
    { key: "fixedAssets",  label: "Fixed assets",   color: "#6366f1" },
    { key: "inventories",  label: "Inventories",    color: "#a78bfa" },
    { key: "receivables",  label: "Receivables",    color: "#22d3ee" },
    { key: "cash",         label: "Cash",           color: "#10b981" },
    { key: "otherAssets",  label: "Other assets",   color: "#94a3b8" },
    { key: "equity",       label: "Equity",         color: "#059669" },
    { key: "ltDebt",       label: "LT debt",        color: "#f97316" },
    { key: "stDebt",       label: "ST fin. debt",   color: "#ef4444" },
    { key: "tradePay",     label: "Trade payables", color: "#fbbf24" },
    { key: "otherLiab",    label: "Other liab.",    color: "#78716c" },
  ];

  return (
    <div>
      {/* Balance-sheet bridge chart — latest year only */}
      {bridgeData && latest?.totalAssets && (
        <div className="mb-4 rounded-lg border bg-white p-3">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-emerald-500 pl-2 mb-2">
            {`Balance-sheet bridge — FY${latest.fiscal_year}`}
          </h3>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={bridgeData} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 100 }}>
              <XAxis type="number" hide tickFormatter={(v: number) => fmtEur(v)} />
              <YAxis type="category" dataKey="side" tick={{ fontSize: 11 }} width={100} />
              <Tooltip formatter={(v) => fmtEur(typeof v === "number" ? v : Number(v) || 0)} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              {BRIDGE_BARS.map((b) => (
                <Bar key={b.key} dataKey={b.key} name={b.label} stackId="bal" fill={b.color} />
              ))}
            </BarChart>
          </ResponsiveContainer>
          <p className="text-[10px] text-slate-400 italic mt-1">
            Top bar = where the value sits (fixed assets, working capital, cash).
            Bottom bar = how it&apos;s funded (equity vs debt). The two bars
            should be the same length.
          </p>
          {negEquity != null && (
            <p className="text-[10px] text-rose-600 mt-1">
              ⚠ Negative equity ({fmtEur(Math.abs(negEquity))}): liabilities
              exceed assets by this amount. Equity bucket above is forced to 0
              so the bars still match visually.
            </p>
          )}
        </div>
      )}

      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2">
          {t("company.bs.title")}
        </h3>
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={() => toggleSection("bs_fa")} className={`text-[11px] px-2.5 py-1.5 md:py-0.5 rounded border transition-colors ${collapsedSections.bs_fa ? "bg-indigo-50 border-indigo-200 text-indigo-600" : "bg-white border-slate-200 text-slate-500 hover:border-slate-300"}`}>
            {collapsedSections.bs_fa ? `\u25b8 ${t("company.bs.faGrouped")}` : `\u25be ${t("company.bs.faExpanded")}`}
          </button>
          <button onClick={() => toggleSection("bs_ca")} className={`text-[11px] px-2.5 py-1.5 md:py-0.5 rounded border transition-colors ${collapsedSections.bs_ca ? "bg-indigo-50 border-indigo-200 text-indigo-600" : "bg-white border-slate-200 text-slate-500 hover:border-slate-300"}`}>
            {collapsedSections.bs_ca ? `\u25b8 ${t("company.bs.caGrouped")}` : `\u25be ${t("company.bs.caExpanded")}`}
          </button>
          <button onClick={() => toggleSection("bs_cl")} className={`text-[11px] px-2.5 py-1.5 md:py-0.5 rounded border transition-colors ${collapsedSections.bs_cl ? "bg-indigo-50 border-indigo-200 text-indigo-600" : "bg-white border-slate-200 text-slate-500 hover:border-slate-300"}`}>
            {collapsedSections.bs_cl ? `\u25b8 ${t("company.bs.clGrouped")}` : `\u25be ${t("company.bs.clExpanded")}`}
          </button>
          <ExportButtons
            onExportCSV={exportBsCsv}
            onPrint={() => window.print()}
          />
        </div>
      </div>
      <div className="rounded-lg border overflow-x-auto bg-white">
        <table className="w-full min-w-[560px] md:min-w-[900px]">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="sticky left-0 z-10 bg-slate-50 px-2 md:px-4 py-2 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[120px] md:w-auto md:min-w-[260px] shadow-[1px_0_0_rgba(226,232,240,1)]">{t("company.bs.lineItem")}</th>
              {renderDeltaHeaders(chronological.map(r => r.fiscal_year))}
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => {
              if (line.group && collapsedSections[line.group]) return null;

              const showSection = line.section && line.section !== lastSection;
              if (line.section) lastSection = line.section;
              return (
                <React.Fragment key={line.key + (line.section || "")}>
                  {showSection && (
                    <tr>
                      <td colSpan={chronological.length * 2} className="sticky left-0 bg-white px-4 pt-3 pb-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest">{line.section}</span>
                      </td>
                    </tr>
                  )}
                  <tr className={`${line.topBorder ? "border-t border-slate-200" : ""} ${line.doubleBorder ? "border-t-2 border-slate-400" : ""}`}>
                    <td className={`sticky left-0 z-[5] bg-white px-2 md:px-4 py-1 text-[11px] md:text-xs whitespace-normal break-words w-[120px] md:w-auto shadow-[1px_0_0_rgba(226,232,240,1)] ${line.bold ? "font-bold text-slate-800" : "text-slate-600"} ${line.indent ? "pl-4 md:pl-8" : ""} ${line.subIndent ? "pl-6 md:pl-12 text-slate-400 italic" : ""}`}>
                      {line.label}
                    </td>
                    {chronologicalBs.map((r, colIdx) => {
                      const prevRow = colIdx > 0 ? chronologicalBs[colIdx - 1] : null;
                      const currentVal = r[line.key] as number | null;
                      const prevVal = prevRow ? (prevRow[line.key] as number | null) : null;
                      return (
                        <React.Fragment key={`bs-${r.fiscal_year}-${line.key}`}>
                          {colIdx > 0 && (
                            <td className="px-0.5 md:px-1 py-1 text-center align-top w-[32px] md:w-[70px]">
                              {renderDelta(currentVal, prevVal)}
                            </td>
                          )}
                          <td className={`px-1.5 md:px-3 py-1 text-right text-[11px] md:text-xs font-mono ${line.bold ? "font-bold" : ""}`}>
                            {fmtCell(r[line.key] as number | null)}
                          </td>
                        </React.Fragment>
                      );
                    })}
                  </tr>
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-[11px] text-slate-400 italic">
        {t("company.bs.footnote")}
      </p>
    </div>
  );
}
