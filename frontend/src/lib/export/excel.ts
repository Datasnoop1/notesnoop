/** Generate a professional multi-sheet Excel company profile report. */

import ExcelJS from "exceljs";
import { BRAND } from "./constants";
import { derivePnlData, deriveCashFlowData, deriveBalanceSheetData, deriveCreditData } from "./data";
import type { ExportData, PnlRow, CashFlowRow, BalanceSheetRow, CreditRow } from "./types";
import { fmtCbe } from "@/lib/format";

// ── Helpers ──────────────────────────────────────────────

function addHeaderBand(ws: ExcelJS.Worksheet, name: string, cbe: string, cols: number) {
  const row = ws.addRow([`${name}  ·  CBE ${fmtCbe(cbe)}  ·  Exported ${new Date().toLocaleDateString("en-GB")}`]);
  row.font = { bold: true, size: 11, color: { argb: BRAND.headerFont } };
  row.fill = { type: "pattern", pattern: "solid", fgColor: { argb: BRAND.headerBg } };
  row.height = 28;
  row.alignment = { vertical: "middle", horizontal: "left" };
  ws.mergeCells(1, 1, 1, Math.max(cols, 2));
  ws.addRow([]);
}

function styleHeaderRow(row: ExcelJS.Row) {
  row.font = { bold: true, size: 9, color: { argb: BRAND.headerFont } };
  row.fill = { type: "pattern", pattern: "solid", fgColor: { argb: BRAND.headerBg } };
  row.alignment = { vertical: "middle" };
  row.height = 22;
}

function eurFmt(ws: ExcelJS.Worksheet, col: number) {
  ws.getColumn(col).numFmt = '#,##0';
}

function pctFmt(ws: ExcelJS.Worksheet, col: number) {
  ws.getColumn(col).numFmt = '0.0"%"';
}

function boldRow(row: ExcelJS.Row) {
  row.font = { bold: true, size: 9 };
}

function sectionRow(ws: ExcelJS.Worksheet, label: string, cols: number) {
  const row = ws.addRow([label]);
  row.font = { bold: true, size: 8, color: { argb: "64748B" } };
  row.fill = { type: "pattern", pattern: "solid", fgColor: { argb: BRAND.sectionBg } };
  ws.mergeCells(row.number, 1, row.number, cols);
}

function download(buffer: ExcelJS.Buffer, name: string) {
  const blob = new Blob([buffer], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Main ─────────────────────────────────────────────────

export async function generateExcelReport(data: ExportData) {
  const wb = new ExcelJS.Workbook();
  wb.creator = "Datasnoop";
  wb.created = new Date();

  const name = data.detail.name || fmtCbe(data.cbe);
  const safeName = name.replace(/[^a-zA-Z0-9_ -]/g, "_").slice(0, 40);

  // 1. Summary sheet
  buildSummary(wb, data);

  // 2. P&L
  if (data.pnl.length > 0) buildPnl(wb, data);

  // 3. Cash Flow
  if (data.cashFlow.length > 0) buildCashFlow(wb, data);

  // 4. Balance Sheet
  if (data.balanceSheet.length > 0) buildBalanceSheet(wb, data);

  // 5. Credit
  if (data.credit.length > 0) buildCredit(wb, data);

  // 6. Administrators
  if (data.administrators.length > 0) buildAdministrators(wb, data);

  // 7. Structure
  if (data.shareholders.length > 0 || data.participatingInterests.length > 0) buildStructure(wb, data);

  // 8. Sector
  if (data.benchmark) buildSector(wb, data);

  const buffer = await wb.xlsx.writeBuffer();
  download(buffer, `${safeName}_Profile.xlsx`);
}

// ── Sheet Builders ───────────────────────────────────────

function buildSummary(wb: ExcelJS.Workbook, data: ExportData) {
  const ws = wb.addWorksheet("Summary");
  ws.columns = [{ width: 22 }, { width: 35 }];
  const d = data.detail;

  addHeaderBand(ws, d.name || "Company Profile", data.cbe, 2);

  sectionRow(ws, "COMPANY DETAILS", 2);
  const info: [string, string][] = [
    ["Company Name", d.name || "—"],
    ["CBE Number", fmtCbe(data.cbe)],
    ["Status", d.status === "AC" ? "Active" : "Inactive"],
    ["Legal Form", d.jf_label || "—"],
    ["Address", [d.street, d.house_number, d.zipcode, d.city].filter(Boolean).join(", ") || "—"],
    ["NACE Code", d.nace_code ? `${d.nace_code} — ${d.nace_label || ""}` : "—"],
    ["Website", d.website || "—"],
    ["Founded", d.start_date || "—"],
  ];
  for (const [label, val] of info) {
    const row = ws.addRow([label, val]);
    row.getCell(1).font = { bold: true, size: 9, color: { argb: "64748B" } };
    row.getCell(2).font = { size: 9 };
  }

  ws.addRow([]);
  // Key financials from latest year
  if (data.pnl.length > 0) {
    const latest = data.pnl[data.pnl.length - 1];
    sectionRow(ws, `KEY FINANCIALS — FY${latest.fiscal_year}`, 2);
    const metrics: [string, number | null, string][] = [
      ["Revenue", latest.revenue, "#,##0"],
      ["EBITDA", latest.ebitda, "#,##0"],
      ["EBITDA Margin", latest.ebitdaMarginPct, "0.0\"%\""],
      ["EBIT", latest.ebit, "#,##0"],
      ["Net Profit", latest.netProfit, "#,##0"],
    ];
    for (const [label, val, fmt] of metrics) {
      const row = ws.addRow([label, val]);
      row.getCell(1).font = { bold: true, size: 9, color: { argb: "64748B" } };
      row.getCell(2).font = { size: 9 };
      row.getCell(2).numFmt = fmt;
    }
  }
}

function buildFinancialSheet(
  wb: ExcelJS.Workbook,
  sheetName: string,
  data: ExportData,
  rows: { fiscal_year: number }[],
  lines: { label: string; key: string; bold?: boolean; section?: string; isPct?: boolean }[]
) {
  const ws = wb.addWorksheet(sheetName);
  const years = rows.map((r) => r.fiscal_year);
  const totalCols = 1 + years.length;

  ws.getColumn(1).width = 32;
  for (let i = 2; i <= totalCols; i++) ws.getColumn(i).width = 16;

  addHeaderBand(ws, data.detail.name || fmtCbe(data.cbe), data.cbe, totalCols);

  // Header row
  const hdr = ws.addRow(["Line Item", ...years.map((y) => `FY${y}`)]);
  styleHeaderRow(hdr);
  for (let i = 2; i <= totalCols; i++) hdr.getCell(i).alignment = { horizontal: "right" };

  let lastSection = "";
  for (const line of lines) {
    if (line.section && line.section !== lastSection) {
      sectionRow(ws, line.section, totalCols);
      lastSection = line.section;
    }
    const vals = rows.map((r) => (r as Record<string, unknown>)[line.key] as number | null ?? null);
    const row = ws.addRow([line.label, ...vals]);
    row.getCell(1).font = { size: 9, bold: !!line.bold, color: { argb: line.bold ? "1E293B" : "475569" } };
    for (let i = 2; i <= totalCols; i++) {
      row.getCell(i).alignment = { horizontal: "right" };
      row.getCell(i).font = { size: 9, bold: !!line.bold };
      row.getCell(i).numFmt = line.isPct ? '0.0"%"' : "#,##0";
    }
    if (line.bold) {
      row.eachCell((cell) => {
        cell.border = { top: { style: "thin", color: { argb: BRAND.lightBorder } } };
      });
    }
  }
}

function buildPnl(wb: ExcelJS.Workbook, data: ExportData) {
  buildFinancialSheet(wb, "P&L", data, data.pnl, [
    { label: "Revenue", key: "revenue", section: "REVENUE" },
    { label: "Cost of Sales", key: "costOfSales" },
    { label: "Gross Profit", key: "grossMargin", bold: true },
    { label: "Personnel Costs", key: "personnel", section: "OPERATING COSTS" },
    { label: "Depreciation & Amortization", key: "da" },
    { label: "Other Operating Costs", key: "otherOpCosts" },
    { label: "EBIT (Operating Profit)", key: "ebit", bold: true },
    { label: "Financial Charges", key: "finCharges", section: "FINANCIAL" },
    { label: "Profit Before Tax", key: "pbt", bold: true },
    { label: "Tax", key: "tax" },
    { label: "Net Profit", key: "netProfit", bold: true },
    { label: "EBITDA", key: "ebitda", bold: true, section: "EBITDA" },
    { label: "EBITDA Margin %", key: "ebitdaMarginPct", isPct: true },
  ]);
}

function buildCashFlow(wb: ExcelJS.Workbook, data: ExportData) {
  buildFinancialSheet(wb, "Cash Flow", data, data.cashFlow, [
    { label: "EBITDA", key: "ebitda", section: "OPERATING ACTIVITIES" },
    { label: "Δ Inventories", key: "deltaInv" },
    { label: "Δ Trade Receivables", key: "deltaRec" },
    { label: "Δ Trade Payables", key: "deltaPay" },
    { label: "Change in Working Capital", key: "wcChange", bold: true },
    { label: "Cash from Operations", key: "cashFromOps", bold: true },
    { label: "CapEx (est.)", key: "capex", section: "INVESTING ACTIVITIES" },
    { label: "Cash from Investing", key: "cashFromInvesting", bold: true },
    { label: "Δ Long-term Debt", key: "deltaLtDebt", section: "FINANCING ACTIVITIES" },
    { label: "Δ Short-term Debt", key: "deltaStDebt" },
    { label: "Δ Equity", key: "deltaEquity" },
    { label: "Cash from Financing", key: "cashFromFinancing", bold: true },
    { label: "NET CASH CHANGE", key: "netCashChange", bold: true },
    { label: "Cash at Start of Year", key: "cashStart" },
    { label: "Cash at End of Year", key: "cashEnd" },
  ]);
}

function buildBalanceSheet(wb: ExcelJS.Workbook, data: ExportData) {
  buildFinancialSheet(wb, "Balance Sheet", data, data.balanceSheet, [
    { label: "Fixed Assets", key: "fixedAssets", section: "NON-CURRENT ASSETS" },
    { label: "Total Non-Current Assets", key: "fixedAssets", bold: true },
    { label: "Inventories", key: "inventories", section: "CURRENT ASSETS" },
    { label: "Trade Receivables", key: "tradeReceivables" },
    { label: "Cash & Cash Equivalents", key: "cash" },
    { label: "Short-term Investments", key: "currentInvestments" },
    { label: "Other Current Assets", key: "otherCurrentAssets" },
    { label: "Total Current Assets", key: "currentAssets", bold: true },
    { label: "TOTAL ASSETS", key: "totalAssets", bold: true },
    { label: "Total Equity", key: "equity", bold: true, section: "EQUITY" },
    { label: "Long-term Debt", key: "ltDebt", section: "NON-CURRENT LIABILITIES" },
    { label: "  of which: Financial Debt", key: "ltFinDebt" },
    { label: "Trade Payables", key: "tradePayables", section: "CURRENT LIABILITIES" },
    { label: "Short-term Financial Debt", key: "stFinDebt" },
    { label: "Other Current Liabilities", key: "otherCurrentLiab" },
    { label: "Total Current Liabilities", key: "totalCurrentLiab", bold: true },
    { label: "TOTAL EQUITY + LIABILITIES", key: "totalLE", bold: true },
  ]);
}

function buildCredit(wb: ExcelJS.Workbook, data: ExportData) {
  buildFinancialSheet(wb, "Credit Analysis", data, data.credit, [
    { label: "Net Debt / EBITDA", key: "netDebtEbitda", section: "LEVERAGE" },
    { label: "Debt / Equity", key: "debtEquity" },
    { label: "Equity Ratio %", key: "equityRatio", isPct: true },
    { label: "Interest Coverage (x)", key: "interestCoverage" },
    { label: "EBITDA Margin %", key: "ebitdaMargin", isPct: true, section: "PROFITABILITY" },
    { label: "Return on Equity %", key: "roe", isPct: true },
  ]);
}

function buildAdministrators(wb: ExcelJS.Workbook, data: ExportData) {
  const ws = wb.addWorksheet("Administrators");
  ws.columns = [{ width: 28 }, { width: 24 }, { width: 10 }, { width: 14 }, { width: 14 }, { width: 16 }];

  addHeaderBand(ws, data.detail.name || fmtCbe(data.cbe), data.cbe, 6);

  const hdr = ws.addRow(["Name", "Role", "Status", "Start", "End", "Identifier"]);
  styleHeaderRow(hdr);

  const now = new Date();
  const current = data.administrators.filter(
    (a) => !a.mandate_end || a.mandate_end === "" || new Date(a.mandate_end) > now
  );
  const past = data.administrators.filter(
    (a) => a.mandate_end && a.mandate_end !== "" && new Date(a.mandate_end) <= now
  );

  if (current.length > 0) {
    sectionRow(ws, "CURRENT ADMINISTRATORS", 6);
    for (const a of current) {
      const row = ws.addRow([a.name, a.role_label || a.role, "Active", a.mandate_start || "", a.mandate_end || "", a.identifier || ""]);
      row.font = { size: 9 };
      row.getCell(3).font = { size: 9, color: { argb: BRAND.greenFont } };
    }
  }
  if (past.length > 0) {
    sectionRow(ws, "PAST ADMINISTRATORS", 6);
    for (const a of past) {
      const row = ws.addRow([a.name, a.role_label || a.role, "Ended", a.mandate_start || "", a.mandate_end || "", a.identifier || ""]);
      row.font = { size: 9, color: { argb: "94A3B8" } };
    }
  }
}

function buildStructure(wb: ExcelJS.Workbook, data: ExportData) {
  const ws = wb.addWorksheet("Structure");
  ws.columns = [{ width: 28 }, { width: 14 }, { width: 14 }, { width: 16 }, { width: 12 }];

  addHeaderBand(ws, data.detail.name || fmtCbe(data.cbe), data.cbe, 5);

  if (data.shareholders.length > 0) {
    sectionRow(ws, "SHAREHOLDERS", 5);
    const hdr = ws.addRow(["Name", "Ownership %", "Type", "Identifier", "Fiscal Year"]);
    styleHeaderRow(hdr);
    for (const s of data.shareholders) {
      const row = ws.addRow([s.name, s.ownership_pct, s.shareholder_type || "", s.identifier || "", s.fiscal_year || ""]);
      row.font = { size: 9 };
      if (s.ownership_pct != null) row.getCell(2).numFmt = '0.0"%"';
    }
    ws.addRow([]);
  }

  if (data.participatingInterests.length > 0) {
    sectionRow(ws, "PARTICIPATING INTERESTS / SUBSIDIARIES", 5);
    const hdr = ws.addRow(["Name", "Ownership %", "Country", "Identifier", "Fiscal Year"]);
    styleHeaderRow(hdr);
    for (const p of data.participatingInterests) {
      const row = ws.addRow([p.name, p.ownership_pct, p.country || "", p.identifier || "", p.fiscal_year || ""]);
      row.font = { size: 9 };
      if (p.ownership_pct != null) row.getCell(2).numFmt = '0.0"%"';
    }
  }
}

function buildSector(wb: ExcelJS.Workbook, data: ExportData) {
  if (!data.benchmark) return;
  const b = data.benchmark;
  const ws = wb.addWorksheet("Sector Benchmark");
  ws.columns = [{ width: 22 }, { width: 16 }, { width: 12 }, { width: 16 }, { width: 16 }, { width: 16 }];

  addHeaderBand(ws, data.detail.name || fmtCbe(data.cbe), data.cbe, 6);

  const infoRow = ws.addRow([`Sector: ${b.nace_label} (${b.nace_code})  ·  ${b.peer_count} peers  ·  FY${b.fiscal_year}`]);
  infoRow.font = { size: 9, italic: true, color: { argb: "64748B" } };
  ws.mergeCells(infoRow.number, 1, infoRow.number, 6);
  ws.addRow([]);

  const hdr = ws.addRow(["Metric", "Company Value", "Percentile", "P25", "Median", "P75"]);
  styleHeaderRow(hdr);

  for (const m of b.benchmarks) {
    const row = ws.addRow([m.metric, m.value, m.percentile != null ? Math.round(m.percentile) : null, m.p25, m.median, m.p75]);
    row.font = { size: 9 };
    for (let i = 2; i <= 6; i++) {
      row.getCell(i).alignment = { horizontal: "right" };
      row.getCell(i).numFmt = m.format === "pct" ? '0.0"%"' : "#,##0";
    }
    if (m.percentile != null) {
      row.getCell(3).numFmt = "0";
    }
  }
}
