/** Generate a professional PDF company profile report. */

import jsPDF from "jspdf";
import "jspdf-autotable";
import { PDF } from "./constants";
import type { ExportData, PnlRow } from "./types";
import { fmtCbe } from "@/lib/format";

// Extend jsPDF type for autoTable
declare module "jspdf" {
  interface jsPDF {
    autoTable: (options: Record<string, unknown>) => jsPDF;
    lastAutoTable: { finalY: number };
  }
}

function fmtVal(v: number | null): string {
  if (v == null) return "—";
  if (Math.abs(v) >= 1_000_000) return `€${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `€${(v / 1_000).toFixed(0)}K`;
  return `€${v.toFixed(0)}`;
}

function fmtRatio(v: number | null, suffix = "x"): string {
  if (v == null || !isFinite(v)) return "—";
  return `${v.toFixed(1)}${suffix}`;
}

export async function generatePdfReport(data: ExportData) {
  const doc = new jsPDF({ orientation: "landscape", unit: "mm", format: "a4" });
  const name = data.detail.name || fmtCbe(data.cbe);
  const pageWidth = doc.internal.pageSize.getWidth();
  let y = 15;

  // ── Cover / Header ──────────────────────────────────────
  // Accent line
  doc.setDrawColor(...PDF.accentLine);
  doc.setLineWidth(1.5);
  doc.line(15, y, pageWidth - 15, y);
  y += 8;

  // Company name
  doc.setFontSize(18);
  doc.setTextColor(...PDF.textDark);
  doc.setFont("helvetica", "bold");
  doc.text(name, 15, y);
  y += 8;

  // Info line
  doc.setFontSize(9);
  doc.setFont("helvetica", "normal");
  doc.setTextColor(...PDF.textMuted);
  const d = data.detail;
  const address = [d.street, d.house_number, d.zipcode, d.city].filter(Boolean).join(", ");
  const infoLine = `CBE ${fmtCbe(data.cbe)}  ·  ${d.status === "AC" ? "Active" : "Inactive"}  ·  ${address}`;
  doc.text(infoLine, 15, y);
  y += 4;
  if (d.nace_code) {
    doc.text(`NACE ${d.nace_code} — ${d.nace_label || ""}`, 15, y);
    y += 4;
  }
  doc.text(`Report generated: ${new Date().toLocaleDateString("en-GB")}`, 15, y);
  y += 8;

  // ── Key Financials ──────────────────────────────────────
  if (data.pnl.length > 0) {
    const latest = data.pnl[data.pnl.length - 1];
    doc.setFontSize(10);
    doc.setFont("helvetica", "bold");
    doc.setTextColor(...PDF.textDark);
    doc.text(`Key Financials — FY${latest.fiscal_year}`, 15, y);
    y += 5;

    doc.autoTable({
      startY: y,
      margin: { left: 15, right: 15 },
      theme: "plain",
      styles: { fontSize: 8.5, cellPadding: 2 },
      columnStyles: {
        0: { fontStyle: "bold", textColor: PDF.textMuted, cellWidth: 35 },
        1: { halign: "right", cellWidth: 25 },
        2: { fontStyle: "bold", textColor: PDF.textMuted, cellWidth: 35 },
        3: { halign: "right", cellWidth: 25 },
        4: { fontStyle: "bold", textColor: PDF.textMuted, cellWidth: 35 },
        5: { halign: "right", cellWidth: 25 },
      },
      body: [
        ["Revenue", fmtVal(latest.revenue), "EBITDA", fmtVal(latest.ebitda), "EBITDA Margin", latest.ebitdaMarginPct != null ? `${latest.ebitdaMarginPct.toFixed(1)}%` : "—"],
        ["EBIT", fmtVal(latest.ebit), "Net Profit", fmtVal(latest.netProfit), "", ""],
      ],
    });
    y = doc.lastAutoTable.finalY + 6;
  }

  // ── Section helper ──────────────────────────────────────
  function sectionTitle(title: string) {
    if (y > doc.internal.pageSize.getHeight() - 30) {
      doc.addPage();
      y = 15;
    }
    doc.setFontSize(10);
    doc.setFont("helvetica", "bold");
    doc.setTextColor(...PDF.textDark);
    doc.text(title, 15, y);
    y += 5;
  }

  function financialTable(
    title: string,
    rows: { fiscal_year: number }[],
    lines: { label: string; key: string; bold?: boolean; section?: string; isPct?: boolean }[]
  ) {
    sectionTitle(title);
    const years = rows.map((r) => `FY${r.fiscal_year}`);
    const head = [["Line Item", ...years]];
    const body: (string | number)[][] = [];

    for (const line of lines) {
      const vals = rows.map((r) => {
        const v = (r as Record<string, unknown>)[line.key] as number | null;
        if (v == null) return "—";
        if (line.isPct) return `${v.toFixed(1)}%`;
        return fmtVal(v);
      });
      body.push([line.label, ...vals]);
    }

    doc.autoTable({
      startY: y,
      margin: { left: 15, right: 15 },
      head,
      body,
      theme: "grid",
      headStyles: { fillColor: PDF.headerBg, textColor: 255, fontSize: 7.5 },
      bodyStyles: { fontSize: 7.5 },
      columnStyles: { 0: { cellWidth: 50 } },
      didParseCell: (hookData: Record<string, unknown>) => {
        const data2 = hookData as { section: string; row: { index: number }; cell: { styles: Record<string, unknown> } };
        if (data2.section === "body") {
          const lineIdx = data2.row.index;
          if (lineIdx < lines.length && lines[lineIdx].bold) {
            data2.cell.styles.fontStyle = "bold";
          }
        }
      },
    });
    y = doc.lastAutoTable.finalY + 8;
  }

  // ── P&L ────────────────────────────────────────────────
  if (data.pnl.length > 0) {
    financialTable("Income Statement", data.pnl, [
      { label: "Revenue", key: "revenue" },
      { label: "Cost of Sales", key: "costOfSales" },
      { label: "Gross Profit", key: "grossMargin", bold: true },
      { label: "Personnel Costs", key: "personnel" },
      { label: "D&A", key: "da" },
      { label: "Other Op. Costs", key: "otherOpCosts" },
      { label: "EBIT", key: "ebit", bold: true },
      { label: "Financial Charges", key: "finCharges" },
      { label: "Profit Before Tax", key: "pbt", bold: true },
      { label: "Tax", key: "tax" },
      { label: "Net Profit", key: "netProfit", bold: true },
      { label: "EBITDA", key: "ebitda", bold: true },
      { label: "EBITDA Margin %", key: "ebitdaMarginPct", isPct: true },
    ]);
  }

  // ── Cash Flow ──────────────────────────────────────────
  if (data.cashFlow.length > 0) {
    financialTable("Cash Flow Statement", data.cashFlow, [
      { label: "EBITDA", key: "ebitda" },
      { label: "Δ Inventories", key: "deltaInv" },
      { label: "Δ Trade Receivables", key: "deltaRec" },
      { label: "Δ Trade Payables", key: "deltaPay" },
      { label: "WC Change", key: "wcChange", bold: true },
      { label: "Cash from Operations", key: "cashFromOps", bold: true },
      { label: "CapEx (est.)", key: "capex" },
      { label: "Cash from Investing", key: "cashFromInvesting", bold: true },
      { label: "Δ LT Debt", key: "deltaLtDebt" },
      { label: "Δ ST Debt", key: "deltaStDebt" },
      { label: "Δ Equity", key: "deltaEquity" },
      { label: "Cash from Financing", key: "cashFromFinancing", bold: true },
      { label: "NET CASH CHANGE", key: "netCashChange", bold: true },
    ]);
  }

  // ── Balance Sheet ──────────────────────────────────────
  if (data.balanceSheet.length > 0) {
    financialTable("Balance Sheet", data.balanceSheet, [
      { label: "Fixed Assets", key: "fixedAssets" },
      { label: "Current Assets", key: "currentAssets" },
      { label: "TOTAL ASSETS", key: "totalAssets", bold: true },
      { label: "Equity", key: "equity", bold: true },
      { label: "LT Debt", key: "ltDebt" },
      { label: "Current Liabilities", key: "totalCurrentLiab" },
      { label: "TOTAL E+L", key: "totalLE", bold: true },
    ]);
  }

  // ── Credit ─────────────────────────────────────────────
  if (data.credit.length > 0) {
    financialTable("Credit Analysis", data.credit, [
      { label: "Net Debt / EBITDA", key: "netDebtEbitda" },
      { label: "Debt / Equity", key: "debtEquity" },
      { label: "Equity Ratio %", key: "equityRatio", isPct: true },
      { label: "Interest Coverage (x)", key: "interestCoverage" },
      { label: "EBITDA Margin %", key: "ebitdaMargin", isPct: true },
      { label: "ROE %", key: "roe", isPct: true },
    ]);
  }

  // ── Administrators ─────────────────────────────────────
  if (data.administrators.length > 0) {
    sectionTitle("Administrators");
    const now = new Date();
    const admRows = data.administrators.map((a) => {
      const active = !a.mandate_end || a.mandate_end === "" || new Date(a.mandate_end) > now;
      return [a.name, a.role_label || a.role, active ? "Active" : "Ended", a.mandate_start || "—", a.mandate_end || "—"];
    });
    doc.autoTable({
      startY: y,
      margin: { left: 15, right: 15 },
      head: [["Name", "Role", "Status", "Start", "End"]],
      body: admRows,
      theme: "grid",
      headStyles: { fillColor: PDF.headerBg, textColor: 255, fontSize: 7.5 },
      bodyStyles: { fontSize: 7.5 },
    });
    y = doc.lastAutoTable.finalY + 8;
  }

  // ── Structure ──────────────────────────────────────────
  if (data.shareholders.length > 0) {
    sectionTitle("Shareholders");
    doc.autoTable({
      startY: y,
      margin: { left: 15, right: 15 },
      head: [["Name", "Ownership %", "Type"]],
      body: data.shareholders.map((s) => [s.name, s.ownership_pct != null ? `${s.ownership_pct.toFixed(1)}%` : "—", s.shareholder_type || "—"]),
      theme: "grid",
      headStyles: { fillColor: PDF.headerBg, textColor: 255, fontSize: 7.5 },
      bodyStyles: { fontSize: 7.5 },
    });
    y = doc.lastAutoTable.finalY + 8;
  }

  if (data.participatingInterests.length > 0) {
    sectionTitle("Participating Interests / Subsidiaries");
    doc.autoTable({
      startY: y,
      margin: { left: 15, right: 15 },
      head: [["Name", "Ownership %", "Country", "Identifier"]],
      body: data.participatingInterests.map((p) => [p.name, p.ownership_pct != null ? `${p.ownership_pct.toFixed(1)}%` : "—", p.country || "—", p.identifier || "—"]),
      theme: "grid",
      headStyles: { fillColor: PDF.headerBg, textColor: 255, fontSize: 7.5 },
      bodyStyles: { fontSize: 7.5 },
    });
    y = doc.lastAutoTable.finalY + 8;
  }

  // ── Sector ─────────────────────────────────────────────
  if (data.benchmark) {
    sectionTitle(`Sector Benchmark — ${data.benchmark.nace_label}`);
    doc.setFontSize(8);
    doc.setFont("helvetica", "normal");
    doc.setTextColor(...PDF.textMuted);
    doc.text(`${data.benchmark.peer_count} peers  ·  FY${data.benchmark.fiscal_year}`, 15, y);
    y += 4;

    doc.autoTable({
      startY: y,
      margin: { left: 15, right: 15 },
      head: [["Metric", "Company", "Percentile", "P25", "Median", "P75"]],
      body: data.benchmark.benchmarks.map((m) => {
        const fmt = (v: number | null) => {
          if (v == null) return "—";
          if (m.format === "pct") return `${v.toFixed(1)}%`;
          return fmtVal(v);
        };
        return [m.metric, fmt(m.value), m.percentile != null ? `P${Math.round(m.percentile)}` : "—", fmt(m.p25), fmt(m.median), fmt(m.p75)];
      }),
      theme: "grid",
      headStyles: { fillColor: PDF.headerBg, textColor: 255, fontSize: 7.5 },
      bodyStyles: { fontSize: 7.5 },
    });
  }

  // ── Footer on all pages ────────────────────────────────
  const pageCount = doc.getNumberOfPages();
  for (let i = 1; i <= pageCount; i++) {
    doc.setPage(i);
    doc.setFontSize(7);
    doc.setTextColor(...PDF.textMuted);
    doc.text(
      `Data Peak  ·  ${name}  ·  Page ${i}/${pageCount}`,
      pageWidth / 2,
      doc.internal.pageSize.getHeight() - 7,
      { align: "center" }
    );
  }

  const safeName = name.replace(/[^a-zA-Z0-9_ -]/g, "_").slice(0, 40);
  doc.save(`${safeName}_Profile.pdf`);
}
