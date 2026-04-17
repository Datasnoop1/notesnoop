/** Generate a standalone Excel file for the Valuation tab (Vlerick M&A Monitor). */

import ExcelJS from "exceljs";
import { BRAND } from "./constants";
import { fmtCbe } from "@/lib/format";
import type { ValuationData } from "@/lib/api";

function download(buffer: ExcelJS.Buffer, name: string) {
  const blob = new Blob([buffer], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export async function generateValuationExcel(
  data: ValuationData,
  companyName: string,
  cbe: string,
  view: "size" | "sector",
) {
  if (data.status !== "ok" || !data.profile) return;

  const { profile, years, vlerick_reference, pro_memoria_note } = data;
  const multiple = view === "size" ? profile.size_multiple : profile.sector_multiple;
  const viewLabel =
    view === "size"
      ? `${profile.size_bracket_label} size bracket`
      : profile.vlerick_sector_label;

  const wb = new ExcelJS.Workbook();
  wb.creator = "Datasnoop";
  wb.created = new Date();

  const ws = wb.addWorksheet("Valuation");

  // Header band
  const headerRow = ws.addRow([
    `${companyName}  ·  CBE ${fmtCbe(cbe)}  ·  Exported ${new Date().toLocaleDateString("en-GB")}`,
  ]);
  headerRow.font = { bold: true, size: 11, color: { argb: BRAND.headerFont } };
  headerRow.fill = { type: "pattern", pattern: "solid", fgColor: { argb: BRAND.headerBg } };
  headerRow.height = 28;
  headerRow.alignment = { vertical: "middle", horizontal: "left" };
  ws.mergeCells(1, 1, 1, 5);
  ws.addRow([]);

  // Section title
  const titleRow = ws.addRow(["Indicative valuation — based on Vlerick M&A Monitor"]);
  titleRow.font = { bold: true, size: 10, color: { argb: "334155" } };
  ws.addRow([]);

  // Meta block
  ws.addRow(["Applied multiple:", `${multiple.toFixed(1)}x`, `(${viewLabel})`]);
  ws.addRow(["Data year:", vlerick_reference.data_year, `(${vlerick_reference.report})`]);
  ws.addRow(["Publisher:", vlerick_reference.publisher]);
  ws.addRow(["Source URL:", vlerick_reference.url]);
  ws.addRow([]);

  // Ladder header
  const yearCols = years.map((y) => (y.fiscal_year ? `FY${y.fiscal_year}` : "—"));
  const ladderHeader = ws.addRow(["Step", ...yearCols]);
  ladderHeader.font = { bold: true, size: 9, color: { argb: BRAND.headerFont } };
  ladderHeader.fill = { type: "pattern", pattern: "solid", fgColor: { argb: BRAND.headerBg } };
  ladderHeader.alignment = { vertical: "middle" };
  ladderHeader.height = 22;

  // Ladder rows
  const addLadderRow = (label: string, values: (number | null)[], opts?: { bold?: boolean; fill?: string }) => {
    const row = ws.addRow([label, ...values]);
    if (opts?.bold) row.font = { bold: true, size: 9 };
    if (opts?.fill) row.fill = { type: "pattern", pattern: "solid", fgColor: { argb: opts.fill } };
    // Number format
    for (let c = 2; c <= 1 + values.length; c++) {
      row.getCell(c).numFmt = "#,##0";
      row.getCell(c).alignment = { horizontal: "right" };
    }
  };

  addLadderRow("EBITDA", years.map((y) => y.ebitda));
  // Multiple row — same value repeated, styled as ratio
  const mRow = ws.addRow(["× Vlerick multiple", ...years.map(() => multiple)]);
  for (let c = 2; c <= 1 + years.length; c++) {
    mRow.getCell(c).numFmt = '0.0"x"';
    mRow.getCell(c).alignment = { horizontal: "right" };
  }
  mRow.font = { color: { argb: "4F46E5" } };
  addLadderRow("= Enterprise Value", years.map((y) => (view === "size" ? y.by_size.enterprise_value : y.by_sector.enterprise_value)), { bold: true });
  addLadderRow("− Financial debt", years.map((y) => y.financial_debt));
  addLadderRow("+ Cash & equivalents", years.map((y) => y.cash_and_equivalents));
  addLadderRow("= Net debt", years.map((y) => y.net_debt), { bold: true, fill: BRAND.sectionBg });
  addLadderRow("= Equity Value", years.map((y) => (view === "size" ? y.by_size.equity_value : y.by_sector.equity_value)), { bold: true, fill: BRAND.greenFill });

  ws.addRow([]);

  // Average EBITDA valuation (3-year avg EBITDA x multiple - latest net debt)
  const validEbitdas = years.map((y) => y.ebitda).filter((v): v is number => v != null);
  if (validEbitdas.length >= 2) {
    const avgEbitda = validEbitdas.reduce((s, v) => s + v, 0) / validEbitdas.length;
    const avgEv = avgEbitda * multiple;
    const latestRow = years[years.length - 1];
    const latestNd = latestRow?.net_debt ?? 0;
    const avgEquity = avgEv - latestNd;

    const avgTitle = ws.addRow([`Average EBITDA valuation (${validEbitdas.length}-year avg)`]);
    avgTitle.font = { bold: true, size: 10, color: { argb: "334155" } };
    const avgSub = ws.addRow(["Avg EBITDA", "× Multiple", "= EV", "− Net debt (latest)", "= Equity value"]);
    avgSub.font = { bold: true, size: 8, color: { argb: "64748B" } };
    const avgRow = ws.addRow([avgEbitda, multiple, avgEv, latestNd, avgEquity]);
    avgRow.font = { bold: true, size: 10 };
    avgRow.getCell(1).numFmt = "#,##0";
    avgRow.getCell(2).numFmt = '0.0"x"';
    avgRow.getCell(3).numFmt = "#,##0";
    avgRow.getCell(4).numFmt = "#,##0";
    avgRow.getCell(5).numFmt = "#,##0";
    avgRow.getCell(5).fill = { type: "pattern", pattern: "solid", fgColor: { argb: BRAND.greenFill } };
    avgRow.getCell(5).font = { bold: true, size: 10, color: { argb: BRAND.greenFont } };
    ws.addRow([]);
  }

  ws.addRow([]);

  // Pro memoria
  if (pro_memoria_note) {
    const pmTitle = ws.addRow(["Pro memoria"]);
    pmTitle.font = { bold: true, size: 9, color: { argb: "B45309" } };
    const pmBody = ws.addRow([pro_memoria_note]);
    pmBody.font = { size: 9, color: { argb: "78350F" } };
    pmBody.alignment = { wrapText: true, vertical: "top" };
    ws.mergeCells(pmBody.number, 1, pmBody.number, 5);
    pmBody.height = 60;
    ws.addRow([]);
  }

  // Footer / disclaimer
  const footer = ws.addRow([
    "This is a reference estimate based on Vlerick M&A Monitor median multiples. " +
      "Actual deal value depends on growth, margins, customer concentration, synergies, and negotiation. Not investment advice.",
  ]);
  footer.font = { italic: true, size: 8, color: { argb: "94A3B8" } };
  footer.alignment = { wrapText: true };
  ws.mergeCells(footer.number, 1, footer.number, 5);
  footer.height = 40;

  // Column widths
  ws.getColumn(1).width = 32;
  for (let c = 2; c <= 4; c++) ws.getColumn(c).width = 16;
  ws.getColumn(5).width = 20;

  const buffer = await wb.xlsx.writeBuffer();
  const safeName = companyName.replace(/[^a-zA-Z0-9_ -]/g, "_").slice(0, 40);
  download(buffer, `${safeName}_valuation.xlsx`);
}
