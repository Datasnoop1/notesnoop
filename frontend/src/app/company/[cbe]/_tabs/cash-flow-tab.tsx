"use client";

import React from "react";
import { AlertTriangle } from "lucide-react";
import ExportButtons from "@/components/export-buttons";
import { useTranslation } from "@/components/language-provider";
import { fmtEur } from "@/lib/format";
import { deriveCashFlow, type CashFlowYear, type RubricData } from "@/lib/cashflow";
import { renderDelta, renderDeltaHeaders } from "../helpers";
import type { FinancialsData } from "../types";
import { PdfOnlyBanner } from "./pdf-only-banner";
import { CashFlowWaterfall } from "./cashflow-waterfall";

interface CashFlowTabProps {
  financials: FinancialsData | null;
  cbe: string;
  companyName: string | null;
  collapsedSections: Record<string, boolean>;
  toggleSection: (key: string) => void;
}

/** Practitioner tolerance for the gap between implied and observed ΔCash.
 *  <2% muted; 2-5% amber; >5% red (M&A, FX, minority interest, revaluation,
 *  or bug). */
const GAP_AMBER_THRESHOLD = 0.02;
const GAP_RED_THRESHOLD = 0.05;

export function CashFlowTab({
  financials,
  cbe,
  companyName,
  collapsedSections,
  toggleSection,
}: CashFlowTabProps) {
  const { t } = useTranslation();

  if (!financials || financials.summary.length < 2) {
    if (financials?.pdf_only) {
      return (
        <div className="py-8">
          <PdfOnlyBanner cbe={cbe} />
        </div>
      );
    }
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        {t("company.cf.noData")}
      </p>
    );
  }

  const rubricData = (financials.rubric_data ?? {}) as RubricData;
  const yearsAsc = [...financials.summary]
    .map((r) => r.fiscal_year)
    .filter((y): y is number => typeof y === "number")
    .sort((a, b) => a - b);

  const cfAllAsc = deriveCashFlow(rubricData, yearsAsc);
  const cfRows = cfAllAsc.slice(1);
  const cfRowsDesc = [...cfRows].reverse();

  if (cfRows.length === 0 || cfRows.every((r) => r.insufficientData)) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        {t("company.cf.noData")}
      </p>
    );
  }

  const anyAuditFailed = cfRows.some((r) => !r.cfoAuditPasses);

  const fmtCell = (v: number | null) => {
    if (v == null) return <span className="text-slate-300">{"\u2014"}</span>;
    const formatted = fmtEur(v);
    return v < 0 ? <span className="text-rose-400">{formatted}</span> : <>{formatted}</>;
  };

  const fmtGapCell = (gap: number | null, observed: number | null) => {
    if (gap == null) return <span className="text-slate-300">{"\u2014"}</span>;
    const ref = observed != null ? Math.abs(observed) : 1;
    const ratio = Math.abs(gap) / Math.max(ref, 1);
    const color =
      ratio > GAP_RED_THRESHOLD
        ? "text-rose-500 font-semibold"
        : ratio > GAP_AMBER_THRESHOLD
          ? "text-amber-600"
          : "text-slate-500";
    return <span className={color}>{fmtEur(gap)}</span>;
  };

  type LineKey = keyof CashFlowYear;

  type CFLine = {
    label: string;
    key: LineKey;
    bold?: boolean;
    indent?: boolean;
    topBorder?: boolean;
    doubleBorder?: boolean;
    section?: string;
    group?: string;
    render?: (row: CashFlowYear) => React.ReactNode;
    /** Drop row when every value is null/0. Keeps uncluttered layouts for
     *  filers that don't disclose e.g. provisions or financial FA moves. */
    dropIfAllEmpty?: boolean;
  };

  // Rows that act as the clickable summary of a collapsible group when
  // that group is collapsed. `wcChange` is the WC subtotal — when cf_wc
  // is collapsed it replaces the five Δ-rows. `cashFromFinancing` is the
  // CFF subtotal — when cf_fin is collapsed it replaces the four
  // financing-movement rows.
  const GROUP_SUMMARY: Partial<Record<LineKey, string>> = {
    wcChange: "cf_wc",
    cashFromFinancing: "cf_fin",
  };

  const lines: CFLine[] = [
    // Opening cash balance — anchors the statement at the top so the
    // reader can trace Opening + CFO + CFI + CFF + Unreconciled = Closing.
    { label: t("company.cf.cashStart"), key: "cashStart", bold: true },

    { label: t("company.cf.ebitda"), key: "ebitda", section: t("company.cf.sectionOperating") },
    // Working capital section: title row FIRST (click to expand/collapse),
    // then the individual Δ rows folded beneath it.
    { label: t("company.cf.wcChange"), key: "wcChange", bold: true, topBorder: true },
    { label: t("company.cf.deltaInventories"), key: "deltaInventories", indent: true, group: "cf_wc", dropIfAllEmpty: true },
    { label: t("company.cf.deltaTradeRec"), key: "deltaTradeReceivables", indent: true, group: "cf_wc" },
    { label: t("company.cf.deltaTradePay"), key: "deltaTradePayables", indent: true, group: "cf_wc" },
    { label: t("company.cf.deltaTaxSocial"), key: "deltaTaxSocialPayables", indent: true, group: "cf_wc", dropIfAllEmpty: true },
    { label: t("company.cf.deltaOtherPay"), key: "deltaOtherPayables", indent: true, group: "cf_wc", dropIfAllEmpty: true },
    // After WC: taxes, then other stuff.
    { label: t("company.cf.incomeTax"), key: "incomeTax", indent: true, dropIfAllEmpty: true },
    { label: t("company.cf.financialIncome"), key: "financialIncome", indent: true, dropIfAllEmpty: true },
    { label: t("company.cf.interestExpense"), key: "interestExpense", indent: true, dropIfAllEmpty: true },
    { label: t("company.cf.writedowns"), key: "writedowns", indent: true, dropIfAllEmpty: true },
    { label: t("company.cf.provisions"), key: "provisions", indent: true, dropIfAllEmpty: true },
    { label: t("company.cf.cashFromOps"), key: "cashFromOps", bold: true, topBorder: true },

    { label: t("company.cf.capex"), key: "capex", indent: true, section: t("company.cf.sectionInvesting") },
    { label: t("company.cf.changeInFinancialAssets"), key: "changeInFinancialAssets", indent: true, dropIfAllEmpty: true },
    { label: t("company.cf.cashFromInvesting"), key: "cashFromInvesting", bold: true, topBorder: true },

    // Financing section: title first, folded movements beneath it.
    { label: t("company.cf.cashFromFinancing"), key: "cashFromFinancing", bold: true, topBorder: true, section: t("company.cf.sectionFinancing") },
    { label: t("company.cf.deltaLtDebt"), key: "deltaLtDebt", indent: true, group: "cf_fin" },
    { label: t("company.cf.deltaStDebt"), key: "deltaStDebt", indent: true, group: "cf_fin" },
    { label: t("company.cf.newCapital"), key: "newCapital", indent: true, group: "cf_fin", dropIfAllEmpty: true },
    { label: t("company.cf.dividendsPaid"), key: "dividendsPaid", indent: true, group: "cf_fin", dropIfAllEmpty: true },

    { label: t("company.cf.impliedCashChange"), key: "impliedCashChange", bold: true, doubleBorder: true, section: t("company.cf.sectionReconciliation") },
    {
      label: t("company.cf.unreconciledGap"),
      key: "unreconciledGap",
      indent: true,
      render: (r) => fmtGapCell(r.unreconciledGap, r.observedCashChange),
    },
    // Closing cash balance — ties to the balance sheet:
    // cashStart + impliedCashChange + unreconciledGap = cashEnd.
    { label: t("company.cf.cashEnd"), key: "cashEnd", bold: true, topBorder: true },
  ];

  const visibleLines = lines.filter((line) => {
    if (!line.dropIfAllEmpty) return true;
    return cfRows.some((r) => {
      const v = r[line.key];
      return typeof v === "number" && v !== 0;
    });
  });

  let lastSection = "";

  function exportCfCsv() {
    const headers = [t("company.cf.lineItem"), ...cfRows.map((r) => `FY${r.fiscalYear}`)];
    const csvLines = visibleLines.map((line) => {
      const cells = cfRowsDesc.map((r) => {
        const v = r[line.key];
        return typeof v === "number" ? String(v) : "";
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
    <div className="space-y-4">
      {financials?.rubric_data && yearsAsc.length > 1 && (
        <CashFlowWaterfall
          rubrics={rubricData}
          fiscalYears={yearsAsc}
        />
      )}

      {anyAuditFailed && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" aria-hidden />
          <span>{t("company.cf.auditWarning")}</span>
        </div>
      )}

      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-cyan-500 pl-2">
          {t("company.cf.title")}
        </h3>
        <ExportButtons onExportCSV={exportCfCsv} onPrint={() => window.print()} />
      </div>
      <div className="rounded-lg border overflow-x-auto bg-white">
        <table className="w-full min-w-[560px] md:min-w-[900px]">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="sticky left-0 z-10 bg-slate-50 px-2 md:px-4 py-2 text-left text-[10px] font-medium text-slate-400 uppercase tracking-wider w-[120px] md:w-auto md:min-w-[260px] shadow-[1px_0_0_rgba(226,232,240,1)]">{t("company.cf.lineItem")}</th>
              {renderDeltaHeaders(cfRows.map((r) => r.fiscalYear))}
            </tr>
          </thead>
          <tbody>
            {visibleLines.map((line) => {
              if (line.group && collapsedSections[line.group]) return null;

              // Is this row the summary of a (possibly-collapsed) group?
              const summaryOf = GROUP_SUMMARY[line.key as LineKey];
              const isCollapsedSummary = summaryOf && collapsedSections[summaryOf];
              const isExpandableSummary = !!summaryOf;

              const showSection = line.section && line.section !== lastSection;
              if (line.section) lastSection = line.section;
              return (
                <React.Fragment key={String(line.key)}>
                  {showSection && (
                    <tr>
                      <td colSpan={cfRows.length * 2} className="sticky left-0 bg-white px-4 pt-3 pb-1">
                        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest">{line.section}</span>
                      </td>
                    </tr>
                  )}
                  <tr className={`${line.topBorder ? "border-t border-slate-200" : ""} ${line.doubleBorder ? "border-t-2 border-slate-400" : ""}`}>
                    <td className={`sticky left-0 z-[5] bg-white px-2 md:px-4 py-1 text-[11px] md:text-xs whitespace-normal break-words w-[120px] md:w-auto shadow-[1px_0_0_rgba(226,232,240,1)] ${line.bold ? "font-bold text-slate-800" : "text-slate-600"} ${line.indent ? "pl-4 md:pl-8" : ""}`}>
                      {isExpandableSummary ? (
                        <button
                          type="button"
                          onClick={() => toggleSection(summaryOf!)}
                          className="inline-flex items-center gap-1 hover:text-indigo-600 transition-colors text-left"
                          aria-expanded={!isCollapsedSummary}
                        >
                          <span className="text-xs leading-none">{isCollapsedSummary ? "\u25b8" : "\u25be"}</span>
                          <span>{line.label}</span>
                        </button>
                      ) : (
                        line.label
                      )}
                    </td>
                    {cfRows.map((r, colIdx) => {
                      const prevRow = colIdx > 0 ? cfRows[colIdx - 1] : null;
                      const currentVal = r[line.key];
                      const prevVal = prevRow ? prevRow[line.key] : null;
                      const currentNum = typeof currentVal === "number" ? currentVal : null;
                      const prevNum = typeof prevVal === "number" ? prevVal : null;
                      return (
                        <React.Fragment key={`cf-${r.fiscalYear}-${String(line.key)}`}>
                          {colIdx > 0 && (
                            <td className="px-0.5 md:px-1 py-1 text-center align-top w-[32px] md:w-[70px]">
                              {line.render ? null : renderDelta(currentNum, prevNum)}
                            </td>
                          )}
                          <td className={`px-1.5 md:px-3 py-1 text-right text-[11px] md:text-xs font-mono ${line.bold ? "font-bold" : ""}`}>
                            {line.render ? line.render(r) : fmtCell(currentNum)}
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
