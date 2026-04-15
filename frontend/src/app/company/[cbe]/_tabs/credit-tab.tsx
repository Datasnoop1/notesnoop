"use client";

import React from "react";
import ExportButtons from "@/components/export-buttons";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { fmtEur } from "@/lib/format";
import type { FinancialsData, CompanyDetail } from "../types";
import { FormulaTooltip, downloadCsv } from "../helpers";

/* ---------- Color threshold functions ---------- */

function leverageColor(v: number | null): string {
  if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
  if (v < 3) return "bg-green-50 border-green-200 text-green-800";
  if (v <= 5) return "bg-amber-50 border-amber-200 text-amber-800";
  return "bg-red-50 border-red-200 text-red-800";
}

function debtEquityColor(v: number | null): string {
  if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
  if (v < 1) return "bg-green-50 border-green-200 text-green-800";
  if (v <= 2) return "bg-amber-50 border-amber-200 text-amber-800";
  return "bg-red-50 border-red-200 text-red-800";
}

function coverageColor(v: number | null): string {
  if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
  if (v >= 3) return "bg-green-50 border-green-200 text-green-800";
  if (v >= 1.5) return "bg-amber-50 border-amber-200 text-amber-800";
  return "bg-red-50 border-red-200 text-red-800";
}

function cashRatioColor(v: number | null): string {
  if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
  if (v >= 1) return "bg-green-50 border-green-200 text-green-800";
  if (v >= 0.5) return "bg-amber-50 border-amber-200 text-amber-800";
  return "bg-red-50 border-red-200 text-red-800";
}

function marginColor(v: number | null): string {
  if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
  if (v >= 15) return "bg-green-50 border-green-200 text-green-800";
  if (v >= 8) return "bg-amber-50 border-amber-200 text-amber-800";
  return "bg-red-50 border-red-200 text-red-800";
}

function roeColor(v: number | null): string {
  if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
  if (v >= 15) return "bg-green-50 border-green-200 text-green-800";
  if (v >= 8) return "bg-amber-50 border-amber-200 text-amber-800";
  return "bg-red-50 border-red-200 text-red-800";
}

function equityRatioColor(v: number | null): string {
  if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
  if (v >= 40) return "bg-green-50 border-green-200 text-green-800";
  if (v >= 20) return "bg-amber-50 border-amber-200 text-amber-800";
  return "bg-red-50 border-red-200 text-red-800";
}

function dscrColor(v: number | null): string {
  if (v == null) return "bg-slate-50 border-slate-200 text-slate-600";
  if (v >= 2) return "bg-green-50 border-green-200 text-green-800";
  if (v >= 1.2) return "bg-amber-50 border-amber-200 text-amber-800";
  return "bg-red-50 border-red-200 text-red-800";
}

/* ---------- Ratio formatters ---------- */

function fmtRatio(v: number | null, suffix = "x"): string {
  if (v == null || !isFinite(v)) return "\u2014";
  return `${v.toFixed(1)}${suffix}`;
}

function fmtDays(v: number | null): string {
  if (v == null || !isFinite(v)) return "\u2014";
  return `${Math.round(v)}d`;
}

/* ---------- Component ---------- */

interface CreditTabProps {
  financials: FinancialsData | null;
  detail: CompanyDetail | null;
  cbe: string;
}

export function CreditTab({ financials, detail, cbe }: CreditTabProps) {
  if (!financials || financials.summary.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        No financial data available for credit analysis.
      </p>
    );
  }

  const sorted = [...financials.summary].sort((a, b) => b.fiscal_year - a.fiscal_year);
  const chronological = [...sorted].reverse();

  // Compute ratios for each year
  const ratios = sorted.map((row) => {
    const grossDebt = (row.lt_financial_debt ?? 0) + (row.st_financial_debt ?? 0);
    const netDebt = grossDebt - (row.cash ?? 0) - (row.current_investments ?? 0);
    const ebitda = row.ebitda;
    const ebit = row.ebit;
    const equity = row.equity;
    const netProfit = row.net_profit;
    const revenue = row.revenue;
    const finCharges = row.financial_charges;
    const tradeRec = row.trade_receivables;
    const tradePay = row.trade_payables;
    const stDebt = row.st_financial_debt;

    const totalAssets = row.total_assets;
    const netDebtEbitda = ebitda && ebitda !== 0 ? netDebt / ebitda : null;
    const debtEquity = equity && equity !== 0 ? grossDebt / equity : null;
    const equityRatio = totalAssets && totalAssets !== 0 ? (equity ?? 0) / totalAssets * 100 : null;
    const interestCoverage = finCharges && finCharges !== 0 ? (ebit ?? 0) / Math.abs(finCharges) : null;
    const cashStDebt = stDebt && stDebt !== 0 ? ((row.cash ?? 0) + (row.current_investments ?? 0)) / stDebt : null;
    const roe = equity && equity !== 0 ? ((netProfit ?? 0) / equity) * 100 : null;
    const ebitdaMargin = revenue && revenue > 0 ? ((ebitda ?? 0) / revenue) * 100 : null;
    const dso = revenue && revenue > 0 ? ((tradeRec ?? 0) / revenue) * 365 : null;
    const dpo = revenue && revenue > 0 ? ((tradePay ?? 0) / revenue) * 365 : null;
    const dscr = (finCharges || stDebt) ? (ebitda ?? 0) / (Math.abs(finCharges ?? 0) + (stDebt ?? 0)) : null;

    return {
      fiscal_year: row.fiscal_year,
      netDebtEbitda,
      debtEquity,
      equityRatio,
      interestCoverage,
      cashStDebt,
      roe,
      ebitdaMargin,
      dso,
      dpo,
      netDebt,
      grossDebt,
      dscr,
    };
  });
  const chronologicalRatios = [...ratios].reverse();

  const latest = ratios[0];
  const latestRow = sorted[0];

  const lr = latestRow; // shorthand for formula details
  const metricCards = [
    { label: "Net Debt / EBITDA", value: fmtRatio(latest.netDebtEbitda), colorFn: leverageColor, raw: latest.netDebtEbitda, formula: "(LT Fin Debt + ST Fin Debt \u2212 Cash \u2212 Investments) / EBITDA", detail: `(${fmtEur(lr.lt_financial_debt)} + ${fmtEur(lr.st_financial_debt)} \u2212 ${fmtEur(lr.cash)} \u2212 ${fmtEur(lr.current_investments)}) / ${fmtEur(lr.ebitda)}` },
    { label: "Debt / Equity", value: fmtRatio(latest.debtEquity), colorFn: debtEquityColor, raw: latest.debtEquity, formula: "(LT Fin Debt + ST Fin Debt) / Equity", detail: `(${fmtEur(lr.lt_financial_debt)} + ${fmtEur(lr.st_financial_debt)}) / ${fmtEur(lr.equity)}` },
    { label: "Equity Ratio", value: fmtRatio(latest.equityRatio, "%"), colorFn: equityRatioColor, raw: latest.equityRatio, formula: "Equity / Total Assets \u00d7 100", detail: `${fmtEur(lr.equity)} / ${fmtEur(lr.total_assets)}` },
    { label: "Interest Coverage", value: fmtRatio(latest.interestCoverage), colorFn: coverageColor, raw: latest.interestCoverage, formula: "EBIT / |Financial Charges|", detail: `${fmtEur(lr.ebit)} / ${fmtEur(lr.financial_charges)}` },
    { label: "Cash / ST Debt", value: fmtRatio(latest.cashStDebt), colorFn: cashRatioColor, raw: latest.cashStDebt, formula: "(Cash + Investments) / ST Financial Debt", detail: `(${fmtEur(lr.cash)} + ${fmtEur(lr.current_investments)}) / ${fmtEur(lr.st_financial_debt)}` },
    { label: "Debt Service", value: fmtRatio(latest.dscr), colorFn: dscrColor, raw: latest.dscr, formula: "EBITDA / (|Fin Charges| + ST Fin Debt)", detail: `${fmtEur(lr.ebitda)} / (${fmtEur(lr.financial_charges)} + ${fmtEur(lr.st_financial_debt)})` },
    { label: "ROE", value: fmtRatio(latest.roe, "%"), colorFn: roeColor, raw: latest.roe, formula: "Net Profit / Equity \u00d7 100", detail: `${fmtEur(lr.net_profit)} / ${fmtEur(lr.equity)}` },
  ];

  function exportCreditCsv() {
    const headers = ["Metric", ...chronologicalRatios.map(r => `FY${r.fiscal_year}`)];
    const lines = [
      { label: "Net Debt / EBITDA", key: "netDebtEbitda" },
      { label: "Debt / Equity", key: "debtEquity" },
      { label: "Equity Ratio %", key: "equityRatio" },
      { label: "Interest Coverage", key: "interestCoverage" },
      { label: "Cash / ST Debt", key: "cashStDebt" },
      { label: "DSCR", key: "dscr" },
      { label: "ROE %", key: "roe" },
      { label: "EBITDA Margin %", key: "ebitdaMargin" },
      { label: "DSO (days)", key: "dso" },
      { label: "DPO (days)", key: "dpo" },
    ];
    const rows = lines.map(l => [l.label, ...chronologicalRatios.map(r => {
      const v = (r as any)[l.key];
      return v != null && isFinite(v) ? v.toFixed(1) : "";
    })]);
    downloadCsv(`${detail?.name || cbe}_credit.csv`, headers, rows);
  }

  return (
    <div className="space-y-6">
      {/* Key Metrics Cards */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-purple-500 pl-2">
            Key Ratios (FY{latest.fiscal_year})
          </h3>
          <ExportButtons onExportCSV={exportCreditCsv} onPrint={() => window.print()} />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-7 gap-2">
          {metricCards.map((m) => (
            <FormulaTooltip key={m.label} formula={m.formula} detail={m.detail}>
              <div className={`rounded-lg border p-2 text-center cursor-default ${m.colorFn(m.raw)}`}>
                <div className="text-[10px] font-medium uppercase tracking-wider opacity-70">{m.label}</div>
                <div className="mt-1 text-base font-bold">{m.value}</div>
              </div>
            </FormulaTooltip>
          ))}
        </div>
      </div>

      {/* Leverage Ratios Table */}
      <div>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-red-500 pl-2">
          Leverage
        </h3>
        <div className="rounded-lg border overflow-x-auto bg-white">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead className="text-xs min-w-[160px]">Metric</TableHead>
                {chronologicalRatios.map((r) => (
                  <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[90px]">FY{r.fiscal_year}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="(LT Fin Debt + ST Fin Debt \u2212 Cash \u2212 Investments) / EBITDA">Net Debt / EBITDA</FormulaTooltip></TableCell>
                {chronologicalRatios.map((r) => (
                  <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.netDebtEbitda)}</TableCell>
                ))}
              </TableRow>
              <TableRow>
                <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="(LT Fin Debt + ST Fin Debt) / Equity">Debt / Equity</FormulaTooltip></TableCell>
                {chronologicalRatios.map((r) => (
                  <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.debtEquity)}</TableCell>
                ))}
              </TableRow>
              <TableRow className="bg-slate-50/50">
                <TableCell className="text-xs text-slate-600 py-1 font-medium"><FormulaTooltip formula="Equity / Total Assets \u00d7 100">Equity Ratio (Equity / Assets)</FormulaTooltip></TableCell>
                {chronologicalRatios.map((r) => (
                  <TableCell key={r.fiscal_year} className={`text-right font-mono text-xs py-1 font-medium ${r.equityRatio != null && r.equityRatio >= 40 ? "text-green-700" : r.equityRatio != null && r.equityRatio >= 20 ? "text-amber-700" : r.equityRatio != null ? "text-rose-500" : ""}`}>{fmtRatio(r.equityRatio, "%")}</TableCell>
                ))}
              </TableRow>
              <TableRow>
                <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="EBIT / |Financial Charges|">Interest Coverage</FormulaTooltip></TableCell>
                {chronologicalRatios.map((r) => (
                  <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.interestCoverage)}</TableCell>
                ))}
              </TableRow>
              <TableRow>
                <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="LT Fin Debt + ST Fin Debt \u2212 Cash \u2212 Investments">Net Debt</FormulaTooltip></TableCell>
                {chronologicalRatios.map((r) => (
                  <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(r.netDebt)}</TableCell>
                ))}
              </TableRow>
              <TableRow className="bg-slate-50/50">
                <TableCell className="text-xs text-slate-600 py-1 font-medium"><FormulaTooltip formula="EBITDA / (|Financial Charges| + ST Financial Debt)">Debt Service (DSCR)</FormulaTooltip></TableCell>
                {chronologicalRatios.map((r) => (
                  <TableCell key={r.fiscal_year} className={`text-right font-mono text-xs py-1 font-medium ${r.dscr != null && r.dscr >= 2 ? "text-green-700" : r.dscr != null && r.dscr >= 1.2 ? "text-amber-700" : r.dscr != null ? "text-rose-500" : ""}`}>{fmtRatio(r.dscr)}</TableCell>
                ))}
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Liquidity */}
      <div>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-amber-500 pl-2">
          Liquidity
        </h3>
        <div className="rounded-lg border overflow-x-auto bg-white">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead className="text-xs min-w-[160px]">Metric</TableHead>
                {chronologicalRatios.map((r) => (
                  <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[90px]">FY{r.fiscal_year}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="(Cash + Investments) / ST Financial Debt">Cash / ST Debt</FormulaTooltip></TableCell>
                {chronologicalRatios.map((r) => (
                  <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.cashStDebt)}</TableCell>
                ))}
              </TableRow>
              <TableRow>
                <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="Cash (54/58) + Current Investments (50/53)">Cash & Investments</FormulaTooltip></TableCell>
                {chronological.map((row) => (
                  <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">
                    {fmtEur(((row.cash ?? 0) + (row.current_investments ?? 0)) || null)}
                  </TableCell>
                ))}
              </TableRow>
              <TableRow>
                <TableCell className="text-xs text-slate-600 py-1">ST Financial Debt</TableCell>
                {chronological.map((row) => (
                  <TableCell key={row.fiscal_year} className="text-right font-mono text-xs py-1">{fmtEur(row.st_financial_debt)}</TableCell>
                ))}
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Profitability */}
      <div>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-green-500 pl-2">
          Profitability
        </h3>
        <div className="rounded-lg border overflow-x-auto bg-white">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead className="text-xs min-w-[160px]">Metric</TableHead>
                {chronologicalRatios.map((r) => (
                  <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[90px]">FY{r.fiscal_year}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="EBITDA / Revenue \u00d7 100">EBITDA Margin</FormulaTooltip></TableCell>
                {chronologicalRatios.map((r) => (
                  <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.ebitdaMargin, "%")}</TableCell>
                ))}
              </TableRow>
              <TableRow>
                <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="Net Profit / Total Equity \u00d7 100">ROE</FormulaTooltip></TableCell>
                {chronologicalRatios.map((r) => (
                  <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtRatio(r.roe, "%")}</TableCell>
                ))}
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Working Capital */}
      <div>
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-blue-500 pl-2">
          Working Capital
        </h3>
        <div className="rounded-lg border overflow-x-auto bg-white">
          <Table>
            <TableHeader>
              <TableRow className="bg-slate-50">
                <TableHead className="text-xs min-w-[160px]">Metric</TableHead>
                {chronologicalRatios.map((r) => (
                  <TableHead key={r.fiscal_year} className="text-right text-xs min-w-[90px]">FY{r.fiscal_year}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="Trade Receivables / Revenue \u00d7 365">DSO (days)</FormulaTooltip></TableCell>
                {chronologicalRatios.map((r) => (
                  <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtDays(r.dso)}</TableCell>
                ))}
              </TableRow>
              <TableRow>
                <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="Trade Payables / Revenue \u00d7 365">DPO (days)</FormulaTooltip></TableCell>
                {chronologicalRatios.map((r) => (
                  <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtDays(r.dpo)}</TableCell>
                ))}
              </TableRow>
              <TableRow>
                <TableCell className="text-xs text-slate-600 py-1"><FormulaTooltip formula="DSO \u2212 DPO (lower is better)">Cash Conversion (DSO - DPO)</FormulaTooltip></TableCell>
                {chronologicalRatios.map((r) => {
                  const ccc = r.dso != null && r.dpo != null ? r.dso - r.dpo : null;
                  return (
                    <TableCell key={r.fiscal_year} className="text-right font-mono text-xs py-1">{fmtDays(ccc)}</TableCell>
                  );
                })}
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </div>

      <p className="text-[10px] text-slate-400 italic">
        Thresholds: Net Debt/EBITDA &lt;3x green, 3-5x amber, &gt;5x red. Interest Coverage &gt;3x green, 1.5-3x amber, &lt;1.5x red. DSCR &ge;2x green, 1.2-2x amber, &lt;1.2x red.
      </p>
    </div>
  );
}
