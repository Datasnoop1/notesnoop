"use client";

import React from "react";
import ExportButtons from "@/components/export-buttons";
import { useTranslation } from "@/components/language-provider";
import { fmtEur } from "@/lib/format";
import { renderDelta, renderDeltaHeaders } from "../helpers";
import type { FinancialsData } from "../types";

/* ---------- Props ---------- */

interface CashFlowTabProps {
  financials: FinancialsData | null;
  cbe: string;
  companyName: string | null;
  collapsedSections: Record<string, boolean>;
  toggleSection: (key: string) => void;
}

/* ---------- Component ---------- */

export function CashFlowTab({
  financials,
  cbe,
  companyName,
  collapsedSections,
  toggleSection,
}: CashFlowTabProps) {
  const { t } = useTranslation();

  if (!financials || financials.summary.length < 2) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        {t("company.cf.noData")}
      </p>
    );
  }

  const sorted = [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year);

  // Helper: format value, red if negative
  const fmtCell = (v: number | null) => {
    if (v == null) return <span className="text-slate-300">{"\u2014"}</span>;
    const formatted = fmtEur(v);
    return v < 0 ? <span className="text-rose-400">{formatted}</span> : <>{formatted}</>;
  };

  const cfRowsDesc = sorted.slice(0, -1).map((row, idx) => {
    const prev = sorted[idx + 1];

    const ebitda = row.ebitda;

    // Working capital deltas (increase in asset = cash outflow = negative)
    const deltaInv = -((row.inventories ?? 0) - (prev.inventories ?? 0));
    const deltaRec = -((row.trade_receivables ?? 0) - (prev.trade_receivables ?? 0));
    const deltaPay = (row.trade_payables ?? 0) - (prev.trade_payables ?? 0);
    const wcChange = deltaInv + deltaRec + deltaPay;

    // Cash from Operations
    const cashFromOps = ebitda != null ? ebitda + wcChange : null;

    // Investing: CapEx estimated as delta fixed assets + D&A
    const capex = -Math.abs((row.fixed_assets ?? 0) - (prev.fixed_assets ?? 0) + Math.abs(row.da ?? 0));
    const cashFromInvesting = capex;

    // Financing
    const deltaLtDebt = (row.lt_financial_debt ?? 0) - (prev.lt_financial_debt ?? 0);
    const deltaStDebt = (row.st_financial_debt ?? 0) - (prev.st_financial_debt ?? 0);
    const deltaEquity = (row.equity ?? 0) - (prev.equity ?? 0);
    const cashFromFinancing = deltaLtDebt + deltaStDebt + deltaEquity;

    // Net cash change
    const netCashChange = cashFromOps != null ? cashFromOps + cashFromInvesting + cashFromFinancing : null;
    const cashStart = (prev.cash ?? 0) + (prev.current_investments ?? 0);
    const cashEnd = (row.cash ?? 0) + (row.current_investments ?? 0);

    return {
      fiscal_year: row.fiscal_year,
      ebitda,
      deltaInv: deltaInv !== 0 ? deltaInv : null,
      deltaRec: deltaRec !== 0 ? deltaRec : null,
      deltaPay: deltaPay !== 0 ? deltaPay : null,
      wcChange: wcChange !== 0 ? wcChange : null,
      cashFromOps,
      capex: capex !== 0 ? capex : null,
      cashFromInvesting,
      deltaLtDebt: deltaLtDebt !== 0 ? deltaLtDebt : null,
      deltaStDebt: deltaStDebt !== 0 ? deltaStDebt : null,
      deltaEquity: deltaEquity !== 0 ? deltaEquity : null,
      cashFromFinancing: cashFromFinancing !== 0 ? cashFromFinancing : null,
      netCashChange,
      cashStart: cashStart || null,
      cashEnd: cashEnd || null,
    };
  });
  const cfRows = [...cfRowsDesc].reverse();

  type CFLine = {
    label: string;
    key: keyof (typeof cfRows)[0];
    bold?: boolean;
    indent?: boolean;
    topBorder?: boolean;
    doubleBorder?: boolean;
    section?: string;
    group?: string;
  };

  const lines: CFLine[] = [
    { label: t("company.cf.ebitda"), key: "ebitda", section: t("company.cf.sectionOperating") },
    { label: t("company.cf.deltaInventories"), key: "deltaInv", indent: true, group: "cf_wc" },
    { label: t("company.cf.deltaTradeRec"), key: "deltaRec", indent: true, group: "cf_wc" },
    { label: t("company.cf.deltaTradePay"), key: "deltaPay", indent: true, group: "cf_wc" },
    { label: t("company.cf.wcChange"), key: "wcChange", bold: true, topBorder: true },
    { label: t("company.cf.cashFromOps"), key: "cashFromOps", bold: true, topBorder: true },
    { label: t("company.cf.capex"), key: "capex", indent: true, section: t("company.cf.sectionInvesting") },
    { label: t("company.cf.cashFromInvesting"), key: "cashFromInvesting", bold: true, topBorder: true },
    { label: t("company.cf.deltaLtDebt"), key: "deltaLtDebt", indent: true, section: t("company.cf.sectionFinancing"), group: "cf_fin" },
    { label: t("company.cf.deltaStDebt"), key: "deltaStDebt", indent: true, group: "cf_fin" },
    { label: t("company.cf.deltaEquity"), key: "deltaEquity", indent: true, group: "cf_fin" },
    { label: t("company.cf.cashFromFinancing"), key: "cashFromFinancing", bold: true, topBorder: true },
    { label: t("company.cf.netCashChange"), key: "netCashChange", bold: true, doubleBorder: true },
    { label: t("company.cf.cashStart"), key: "cashStart", indent: true },
    { label: t("company.cf.cashEnd"), key: "cashEnd", indent: true },
  ];

  let lastSection = "";

  function exportCfCsv() {
    const headers = [t("company.cf.lineItem"), ...cfRows.map(r => `FY${r.fiscal_year}`)];
    const csvLines = lines.map(line => {
      const cells = cfRowsDesc.map(r => {
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
    a.download = `${companyName || cbe}_cash_flow.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-cyan-500 pl-2">
          {t("company.cf.title")}
        </h3>
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={() => toggleSection("cf_wc")} className={`text-[11px] px-2.5 py-1.5 md:py-0.5 rounded border transition-colors ${collapsedSections.cf_wc ? "bg-cyan-50 border-cyan-200 text-cyan-600" : "bg-white border-slate-200 text-slate-500 hover:border-slate-300"}`}>
            {collapsedSections.cf_wc ? `\u25b8 ${t("company.cf.wcGrouped")}` : `\u25be ${t("company.cf.wcExpanded")}`}
          </button>
          <button onClick={() => toggleSection("cf_fin")} className={`text-[11px] px-2.5 py-1.5 md:py-0.5 rounded border transition-colors ${collapsedSections.cf_fin ? "bg-cyan-50 border-cyan-200 text-cyan-600" : "bg-white border-slate-200 text-slate-500 hover:border-slate-300"}`}>
            {collapsedSections.cf_fin ? `\u25b8 ${t("company.cf.finGrouped")}` : `\u25be ${t("company.cf.finExpanded")}`}
          </button>
          <ExportButtons onExportCSV={exportCfCsv} onPrint={() => window.print()} />
        </div>
      </div>
      <div className="rounded-lg border overflow-x-auto bg-white">
        <table className="w-full min-w-[900px]">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="sticky left-0 z-10 bg-slate-50 px-2 md:px-4 py-2 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[120px] md:w-auto md:min-w-[260px] shadow-[1px_0_0_rgba(226,232,240,1)]">{t("company.cf.lineItem")}</th>
              {renderDeltaHeaders(cfRows.map(r => r.fiscal_year))}
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => {
              if (line.group && collapsedSections[line.group]) return null;

              const showSection = line.section && line.section !== lastSection;
              if (line.section) lastSection = line.section;
              return (
                <React.Fragment key={line.key}>
                  {showSection && (
                    <tr>
                      <td colSpan={cfRows.length * 2} className="sticky left-0 bg-white px-4 pt-3 pb-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest">{line.section}</span>
                      </td>
                    </tr>
                  )}
                  <tr className={`${line.topBorder ? "border-t border-slate-200" : ""} ${line.doubleBorder ? "border-t-2 border-slate-400" : ""}`}>
                    <td className={`sticky left-0 z-[5] bg-white px-2 md:px-4 py-1 text-[11px] md:text-xs whitespace-normal break-words w-[120px] md:w-auto shadow-[1px_0_0_rgba(226,232,240,1)] ${line.bold ? "font-bold text-slate-800" : "text-slate-600"} ${line.indent ? "pl-4 md:pl-8" : ""}`}>
                      {line.label}
                    </td>
                    {cfRows.map((r, colIdx) => {
                      const prevRow = colIdx > 0 ? cfRows[colIdx - 1] : null;
                      const currentVal = r[line.key] as number | null;
                      const prevVal = prevRow ? (prevRow[line.key] as number | null) : null;
                      return (
                        <React.Fragment key={`cf-${r.fiscal_year}-${line.key}`}>
                          {colIdx > 0 && (
                            <td className="px-0.5 md:px-1 py-1 text-center align-top w-[40px] md:w-[70px]">
                              {renderDelta(currentVal, prevVal)}
                            </td>
                          )}
                          <td className={`px-2 md:px-3 py-1 text-right text-[11px] md:text-xs font-mono ${line.bold ? "font-bold" : ""}`}>
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
        {t("company.cf.footnote")}
      </p>
    </div>
  );
}
