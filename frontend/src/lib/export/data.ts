/** Data derivation functions — extract from raw financial rows into export-ready shapes.
 *  Logic mirrors the inline derivations in company/[cbe]/page.tsx. */

import type { FinancialRow, PnlRow, CashFlowRow, BalanceSheetRow, CreditRow } from "./types";

export function derivePnlData(summary: FinancialRow[]): PnlRow[] {
  const sorted = [...summary].sort((a, b) => a.fiscal_year - b.fiscal_year); // chronological
  return sorted.map((row) => {
    const revenue = row.revenue;
    const grossMargin = row.gross_margin;
    const costOfSales = revenue != null && grossMargin != null ? -(revenue - grossMargin) : null;
    const personnel = row.personnel_costs != null ? -Math.abs(row.personnel_costs) : null;
    const da = row.da != null ? -Math.abs(row.da) : null;
    const ebit = row.ebit;
    const otherOpCosts =
      grossMargin != null && ebit != null
        ? -(grossMargin - ebit - Math.abs(row.personnel_costs ?? 0) - Math.abs(row.da ?? 0))
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
}

export function deriveCashFlowData(summary: FinancialRow[]): CashFlowRow[] {
  const sorted = [...summary].sort((a, b) => a.fiscal_year - b.fiscal_year);
  if (sorted.length < 2) return [];

  return sorted.slice(1).map((row, idx) => {
    const prev = sorted[idx];
    const ebitda = row.ebitda;
    const deltaInv = -((row.inventories ?? 0) - (prev.inventories ?? 0));
    const deltaRec = -((row.trade_receivables ?? 0) - (prev.trade_receivables ?? 0));
    const deltaPay = (row.trade_payables ?? 0) - (prev.trade_payables ?? 0);
    const wcChange = deltaInv + deltaRec + deltaPay;
    const cashFromOps = ebitda != null ? ebitda + wcChange : null;
    const capex = -Math.abs((row.fixed_assets ?? 0) - (prev.fixed_assets ?? 0) + Math.abs(row.da ?? 0));
    const deltaLtDebt = (row.lt_financial_debt ?? 0) - (prev.lt_financial_debt ?? 0);
    const deltaStDebt = (row.st_financial_debt ?? 0) - (prev.st_financial_debt ?? 0);
    const deltaEquity = (row.equity ?? 0) - (prev.equity ?? 0);
    const cashFromFinancing = deltaLtDebt + deltaStDebt + deltaEquity;
    const netCashChange = cashFromOps != null ? cashFromOps + capex + cashFromFinancing : null;

    return {
      fiscal_year: row.fiscal_year,
      ebitda,
      deltaInv: deltaInv !== 0 ? deltaInv : null,
      deltaRec: deltaRec !== 0 ? deltaRec : null,
      deltaPay: deltaPay !== 0 ? deltaPay : null,
      wcChange: wcChange !== 0 ? wcChange : null,
      cashFromOps,
      capex: capex !== 0 ? capex : null,
      cashFromInvesting: capex,
      deltaLtDebt: deltaLtDebt !== 0 ? deltaLtDebt : null,
      deltaStDebt: deltaStDebt !== 0 ? deltaStDebt : null,
      deltaEquity: deltaEquity !== 0 ? deltaEquity : null,
      cashFromFinancing: cashFromFinancing !== 0 ? cashFromFinancing : null,
      netCashChange,
      cashStart: (prev.cash ?? 0) + (prev.current_investments ?? 0) || null,
      cashEnd: (row.cash ?? 0) + (row.current_investments ?? 0) || null,
    };
  });
}

export function deriveBalanceSheetData(summary: FinancialRow[]): BalanceSheetRow[] {
  const sorted = [...summary].sort((a, b) => a.fiscal_year - b.fiscal_year);
  return sorted.map((row) => {
    const fixedAssets = row.fixed_assets ?? null;
    const totalAssets = row.total_assets ?? null;
    const currentAssets = totalAssets != null && fixedAssets != null ? totalAssets - fixedAssets : null;
    const equity = row.equity ?? null;
    const ltDebt = row.lt_debt ?? null;
    const totalCurrentLiab =
      totalAssets != null && equity != null && ltDebt != null ? totalAssets - equity - ltDebt : null;
    const otherCurrentLiab = totalCurrentLiab != null
      ? totalCurrentLiab - (row.st_financial_debt ?? 0) - (row.trade_payables ?? 0)
      : null;

    return {
      fiscal_year: row.fiscal_year,
      fixedAssets,
      currentAssets,
      inventories: row.inventories ?? null,
      tradeReceivables: row.trade_receivables ?? null,
      cash: row.cash ?? null,
      currentInvestments: row.current_investments ?? null,
      otherCurrentAssets:
        currentAssets != null
          ? currentAssets -
            (row.inventories ?? 0) -
            (row.trade_receivables ?? 0) -
            (row.cash ?? 0) -
            (row.current_investments ?? 0)
          : null,
      totalAssets,
      equity,
      ltDebt,
      ltFinDebt: row.lt_financial_debt ?? null,
      tradePayables: row.trade_payables ?? null,
      stFinDebt: row.st_financial_debt ?? null,
      otherCurrentLiab:
        otherCurrentLiab != null && Math.abs(otherCurrentLiab) > 0.5 ? otherCurrentLiab : null,
      totalCurrentLiab,
      totalLE: totalAssets,
    };
  });
}

export function deriveCreditData(summary: FinancialRow[]): CreditRow[] {
  const sorted = [...summary].sort((a, b) => a.fiscal_year - b.fiscal_year);
  return sorted.map((row) => {
    const grossDebt = (row.lt_financial_debt ?? 0) + (row.st_financial_debt ?? 0);
    const netDebt = grossDebt - (row.cash ?? 0) - (row.current_investments ?? 0);
    const ebitda = row.ebitda;
    const ebit = row.ebit;

    return {
      fiscal_year: row.fiscal_year,
      netDebtEbitda: ebitda && ebitda !== 0 ? netDebt / ebitda : null,
      debtEquity: row.equity && row.equity !== 0 ? grossDebt / row.equity : null,
      equityRatio: row.total_assets && row.total_assets !== 0 ? ((row.equity ?? 0) / row.total_assets) * 100 : null,
      interestCoverage:
        row.financial_charges && Math.abs(row.financial_charges) > 0 && ebit != null
          ? ebit / Math.abs(row.financial_charges)
          : null,
      ebitdaMargin:
        row.revenue && row.revenue !== 0 && ebitda != null ? (ebitda / row.revenue) * 100 : null,
      roe:
        row.equity && row.equity !== 0 && row.net_profit != null
          ? (row.net_profit / row.equity) * 100
          : null,
    };
  });
}
