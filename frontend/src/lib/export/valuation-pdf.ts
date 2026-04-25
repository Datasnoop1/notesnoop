/** Single-page A4 PDF of the Valuation tab (Vlerick M&A Monitor). */

import jsPDF from "jspdf";
import autoTable from "jspdf-autotable";
import { PDF } from "./constants";
import { fmtCbe } from "@/lib/format";
import type { ValuationData } from "@/lib/api";

function fmtVal(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—";
  const neg = v < 0;
  const a = Math.abs(v);
  let s: string;
  if (a >= 1e9) s = `€${(a / 1e9).toFixed(1)}B`;
  else if (a >= 1e6) s = `€${(a / 1e6).toFixed(1)}M`;
  else if (a >= 1e3) s = `€${(a / 1e3).toFixed(0)}K`;
  else s = `€${a.toFixed(0)}`;
  return neg ? `-${s}` : s;
}

function fmtMult(v: number): string {
  return `${v.toFixed(1)}×`;
}

export async function generateValuationPdf(
  data: ValuationData,
  companyName: string,
  cbe: string,
  view: "size" | "sector",
) {
  if (data.status !== "ok" || !data.profile) {
    throw new Error("No valuation data available to export");
  }

  const { profile, years, vlerick_reference, pro_memoria_note } = data;
  const multiple = view === "size" ? profile.size_multiple : profile.sector_multiple;
  const viewLabel =
    view === "size"
      ? `${profile.size_bracket_label} size bracket`
      : profile.vlerick_sector_label;

  const doc = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });
  const pageW = doc.internal.pageSize.getWidth();
  const margin = 15;
  let y = 12;

  // Accent line
  doc.setDrawColor(...PDF.accentLine);
  doc.setLineWidth(1.2);
  doc.line(margin, y, pageW - margin, y);
  y += 6;

  // Company name
  doc.setFont("helvetica", "bold");
  doc.setFontSize(16);
  doc.setTextColor(...PDF.textDark);
  doc.text(companyName, margin, y);
  y += 5;

  // CBE + meta
  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  doc.setTextColor(...PDF.textMuted);
  const meta: string[] = [`CBE ${fmtCbe(cbe)}`];
  if (profile.nace_code) meta.push(`NACE ${profile.nace_code}`);
  meta.push(`Exported ${new Date().toLocaleDateString("en-GB")}`);
  doc.text(meta.join("  ·  "), margin, y);
  y += 6;

  // Indicative valuation subtitle
  doc.setFont("helvetica", "bold");
  doc.setFontSize(10);
  doc.setTextColor(...PDF.textDark);
  doc.text("Indicative valuation", margin, y);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  doc.setTextColor(...PDF.textMuted);
  doc.text(
    `Based on ${vlerick_reference.report} (Vlerick Business School)`,
    margin + 34,
    y,
  );
  y += 5;

  // Snapshot row — 4 boxes
  const latest = years[years.length - 1];
  const latestEv = view === "size" ? latest?.by_size.enterprise_value : latest?.by_sector.enterprise_value;
  const latestEq = view === "size" ? latest?.by_size.equity_value : latest?.by_sector.equity_value;
  const fyLabel = latest?.fiscal_year ? `FY${latest.fiscal_year}` : "Latest";

  const boxW = (pageW - 2 * margin) / 4;
  const boxH = 16;
  const drawBox = (i: number, label: string, value: string, sub: string, highlight = false) => {
    const x = margin + i * boxW;
    doc.setDrawColor(...PDF.sectionBg);
    doc.setLineWidth(0.3);
    doc.roundedRect(x + 1, y, boxW - 2, boxH, 1, 1);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(6.5);
    doc.setTextColor(...PDF.textMuted);
    doc.text(label.toUpperCase(), x + 3, y + 3.5);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(13);
    doc.setTextColor(...(highlight ? PDF.accentLine : PDF.textDark));
    doc.text(value, x + 3, y + 10);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(6.5);
    doc.setTextColor(...PDF.textMuted);
    doc.text(sub, x + 3, y + 14);
  };
  drawBox(0, "Applied multiple", fmtMult(multiple), viewLabel);
  drawBox(1, `EBITDA (${fyLabel})`, fmtVal(latest?.ebitda ?? null), "Profit before int., tax & D&A");
  drawBox(2, "Enterprise value", fmtVal(latestEv ?? null), "What a buyer pays");
  drawBox(3, "Equity value", fmtVal(latestEq ?? null), "Shareholders receive", true);
  y += boxH + 5;

  // Average EBITDA valuation strip — positive years only, mirrors UI.
  const positiveEbitdas = years.map((y2) => y2.ebitda).filter((v): v is number => v != null && v > 0);
  if (positiveEbitdas.length >= 2) {
    const avgEbitda = positiveEbitdas.reduce((s, v) => s + v, 0) / positiveEbitdas.length;
    const avgEv = avgEbitda * multiple;
    const latestNd = latest?.net_debt ?? 0;
    const avgEquity = avgEv - latestNd;
    const totalReported = years.filter((y2) => y2.ebitda != null).length;
    const avgTitleText = positiveEbitdas.length === totalReported
      ? `AVERAGE EBITDA VALUATION (${positiveEbitdas.length}-YEAR)`
      : `AVERAGE EBITDA VALUATION (${positiveEbitdas.length} OF ${totalReported} YEARS \u2014 LOSS-MAKING EXCLUDED)`;

    doc.setDrawColor(...PDF.sectionBg);
    doc.setFillColor(...PDF.sectionBg);
    doc.roundedRect(margin, y, pageW - 2 * margin, 14, 1, 1, "F");
    doc.setFont("helvetica", "bold");
    doc.setFontSize(7);
    doc.setTextColor(...PDF.textDark);
    doc.text(avgTitleText, margin + 3, y + 4.5);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(7);
    doc.setTextColor(...PDF.textMuted);
    const formula =
      `Avg EBITDA ${fmtVal(avgEbitda)}  ×  ${fmtMult(multiple)}  =  EV ${fmtVal(avgEv)}  −  Net debt ${fmtVal(latestNd)} (latest)  =  `;
    doc.text(formula, margin + 3, y + 10.5);
    const formulaW = doc.getTextWidth(formula);
    doc.setFont("helvetica", "bold");
    doc.setTextColor(5, 150, 105); // emerald-600
    doc.text(`Equity ${fmtVal(avgEquity)}`, margin + 3 + formulaW, y + 10.5);
    y += 14 + 5;
  }

  // 3-year ladder
  doc.setFont("helvetica", "bold");
  doc.setFontSize(9);
  doc.setTextColor(...PDF.textDark);
  doc.text("Three-year valuation ladder", margin, y);
  y += 3;

  const yearHeaders = years.map((y2) => (y2.fiscal_year ? `FY${y2.fiscal_year}` : "—"));
  const head = [["Step", ...yearHeaders]];
  const body = [
    ["EBITDA", ...years.map((y2) => fmtVal(y2.ebitda))],
    [`× Vlerick M&A Monitor multiple (${viewLabel})`, ...years.map(() => fmtMult(multiple))],
    [
      "= Enterprise Value",
      ...years.map((y2) => fmtVal(view === "size" ? y2.by_size.enterprise_value : y2.by_sector.enterprise_value)),
    ],
    ["− Financial debt", ...years.map((y2) => fmtVal(y2.financial_debt))],
    ["+ Cash & equivalents", ...years.map((y2) => fmtVal(y2.cash_and_equivalents))],
    ["= Net debt", ...years.map((y2) => fmtVal(y2.net_debt))],
    [
      "= Equity Value",
      ...years.map((y2) => fmtVal(view === "size" ? y2.by_size.equity_value : y2.by_sector.equity_value)),
    ],
  ];

  autoTable(doc, {
    startY: y,
    margin: { left: margin, right: margin },
    head,
    body,
    theme: "grid",
    headStyles: { fillColor: PDF.headerBg, textColor: 255, fontSize: 8, cellPadding: 1.5 },
    bodyStyles: { fontSize: 8, cellPadding: 1.5 },
    columnStyles: {
      0: { cellWidth: 60, fontStyle: "normal" },
    },
    didParseCell: (hookData) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const d2 = hookData as any;
      if (d2.section === "body") {
        const i = d2.row.index;
        if (d2.column.index > 0) d2.cell.styles.halign = "right";
        if (i === 2 || i === 5 || i === 6) d2.cell.styles.fontStyle = "bold";
        if (i === 6) {
          d2.cell.styles.fillColor = [236, 253, 245]; // emerald-50
          d2.cell.styles.textColor = [4, 120, 87];
        }
        if (i === 1) d2.cell.styles.textColor = [13, 115, 119]; // brand teal
      }
    },
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  y = ((doc as any).lastAutoTable?.finalY ?? y + 50) + 4;

  // Pro memoria
  if (pro_memoria_note && y < 245) {
    doc.setFont("helvetica", "bold");
    doc.setFontSize(7);
    doc.setTextColor(180, 83, 9); // amber-700
    doc.text("PRO MEMORIA", margin, y);
    y += 3;
    doc.setFont("helvetica", "normal");
    doc.setFontSize(7);
    doc.setTextColor(120, 53, 15); // amber-900
    const wrapped = doc.splitTextToSize(pro_memoria_note, pageW - 2 * margin);
    doc.text(wrapped, margin, y);
    y += wrapped.length * 2.7 + 3;
  }

  // Footer (bottom of page)
  const pageH = doc.internal.pageSize.getHeight();
  const footerY = pageH - 18;
  doc.setDrawColor(...PDF.sectionBg);
  doc.setLineWidth(0.3);
  doc.line(margin, footerY, pageW - margin, footerY);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(6.5);
  doc.setTextColor(...PDF.textMuted);
  doc.text(
    `Source: ${vlerick_reference.report} — ${vlerick_reference.publisher}`,
    margin,
    footerY + 3.5,
  );
  doc.setFontSize(6);
  doc.setTextColor(148, 163, 184); // slate-400
  const disclaimer =
    "This is a reference estimate based on Vlerick M&A Monitor median multiples. Actual deal value depends on growth, margins, customer concentration, synergies, and negotiation. Not investment advice.";
  const wrapDis = doc.splitTextToSize(disclaimer, pageW - 2 * margin);
  doc.text(wrapDis, margin, footerY + 7);
  doc.setFontSize(6);
  doc.setTextColor(...PDF.textMuted);
  doc.text(vlerick_reference.url, margin, footerY + 14);

  const safeName = companyName.replace(/[^a-zA-Z0-9_ -]/g, "_").slice(0, 40);
  doc.save(`${safeName}_valuation.pdf`);
}
