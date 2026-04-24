"use client";

import React from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { fmtEur } from "@/lib/format";
import { ChevronRight } from "lucide-react";

/* EBITDA metric tree — operator-requested drill-down (#11).
 *
 * Shows how EBITDA for a given fiscal year is composed:
 *
 *   Revenue
 *     − Materials
 *     − Services
 *     = Gross margin  (% of revenue)
 *     − Personnel
 *     − Other OpEx
 *     = EBITDA        (% of revenue)
 *
 * Each row has a label, a signed value, and optional percent-of-revenue.
 * When revenue is missing (abbreviated-scheme filers), we start from gross
 * margin — matching the waterfall's fallback.
 */

interface Props {
  open: boolean;
  onClose: () => void;
  fiscalYear: number;
  revenue: number | null;
  grossMargin: number | null;
  materials: number | null;
  services: number | null;
  personnel: number | null;
  otherOpex: number | null;
  ebitda: number | null;
}

type Kind = "header" | "deduction" | "subtotal";

interface Row {
  label: string;
  value: number | null;
  kind: Kind;
  pctOfRevenue?: string;
  indent?: boolean;
}

const signedEur = (v: number | null, kind: Kind): string => {
  if (v == null) return "—";
  if (kind === "deduction") return `\u2212${fmtEur(Math.abs(v))}`;
  return fmtEur(v);
};

export function EbitdaDrilldown({
  open,
  onClose,
  fiscalYear,
  revenue,
  grossMargin,
  materials,
  services,
  personnel,
  otherOpex,
  ebitda,
}: Props) {
  const hasRevenue = revenue != null && revenue > 0;
  const pct = (v: number | null): string | undefined => {
    if (!hasRevenue || v == null) return undefined;
    return `${(v / (revenue as number) * 100).toFixed(1)}%`;
  };

  // Reconciling residuals so the tree sums exactly to the shown EBITDA,
  // even if the sum of raw rubrics diverges slightly from the filed
  // subtotal. "Other cost of sales" lands below Revenue→GM, "Other op
  // costs" lands below GM→EBITDA.
  const cosKnown = (materials ?? 0) + (services ?? 0);
  const cosTotal = hasRevenue && grossMargin != null ? (revenue as number) - grossMargin : null;
  const cosRecon = cosTotal != null ? cosTotal - cosKnown : 0;

  const opexKnown = (personnel ?? 0) + (otherOpex ?? 0);
  const opexTotal = grossMargin != null && ebitda != null ? grossMargin - ebitda : null;
  const opexRecon = opexTotal != null ? opexTotal - opexKnown : 0;

  const hasGrossMargin = grossMargin != null && grossMargin > 0;

  const rows: Row[] = [];
  if (hasRevenue) {
    rows.push({ label: "Revenue", value: revenue, kind: "header", pctOfRevenue: "100.0%" });
    if (hasGrossMargin) {
      // Only break out cost-of-sales against a filed gross margin. Without
      // it, rubrics 60 + 61 aren't a reliable CoS proxy (retailers book
      // services separately from goods), so we show the flat Revenue →
      // EBITDA tree instead.
      if (materials) rows.push({ label: "Materials", value: materials, kind: "deduction", indent: true, pctOfRevenue: pct(materials) });
      if (services) rows.push({ label: "Services", value: services, kind: "deduction", indent: true, pctOfRevenue: pct(services) });
      if (Math.abs(cosRecon) > 0.5) {
        rows.push({
          label: cosRecon > 0 ? "Other cost of sales" : "Other revenue",
          value: Math.abs(cosRecon),
          kind: "deduction",
          indent: true,
        });
      }
    }
  }
  if (hasGrossMargin) {
    rows.push({
      label: "Gross margin",
      value: grossMargin,
      kind: "subtotal",
      pctOfRevenue: pct(grossMargin),
    });
    if (personnel) rows.push({ label: "Personnel", value: personnel, kind: "deduction", indent: true, pctOfRevenue: pct(personnel) });
    if (otherOpex) rows.push({ label: "Other operating costs", value: otherOpex, kind: "deduction", indent: true, pctOfRevenue: pct(otherOpex) });
    if (Math.abs(opexRecon) > 0.5) {
      rows.push({
        label: opexRecon > 0 ? "Other op. costs (residual)" : "Other op. income",
        value: Math.abs(opexRecon),
        kind: "deduction",
        indent: true,
      });
    }
  } else if (hasRevenue) {
    // Gross margin not in this filing — deduct all op costs from revenue
    // directly.
    if (materials) rows.push({ label: "Materials", value: materials, kind: "deduction", indent: true, pctOfRevenue: pct(materials) });
    if (services) rows.push({ label: "Services", value: services, kind: "deduction", indent: true, pctOfRevenue: pct(services) });
    if (personnel) rows.push({ label: "Personnel", value: personnel, kind: "deduction", indent: true, pctOfRevenue: pct(personnel) });
    if (otherOpex) rows.push({ label: "Other operating costs", value: otherOpex, kind: "deduction", indent: true, pctOfRevenue: pct(otherOpex) });
  }
  rows.push({
    label: "EBITDA",
    value: ebitda,
    kind: "subtotal",
    pctOfRevenue: pct(ebitda),
  });

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="sm:max-w-md p-0 overflow-hidden">
        <DialogHeader className="px-4 py-3 border-b border-slate-100">
          <DialogTitle className="text-sm font-semibold text-slate-800">
            EBITDA drill-down
            <span className="ml-2 text-[11px] font-normal text-slate-400">FY{fiscalYear}</span>
          </DialogTitle>
        </DialogHeader>
        <div className="px-4 py-3">
          <table className="w-full text-[12px]">
            <tbody>
              {rows.map((r, i) => {
                const isSubtotal = r.kind === "subtotal";
                const isDed = r.kind === "deduction";
                return (
                  <tr
                    key={`${r.label}-${i}`}
                    className={isSubtotal ? "border-t border-slate-200" : ""}
                  >
                    <td
                      className={`py-1.5 ${r.indent ? "pl-5 text-slate-500" : "pl-0"} ${
                        isSubtotal ? "font-semibold text-slate-800" : ""
                      }`}
                    >
                      {r.indent && <ChevronRight className="inline h-3 w-3 text-slate-300 -mt-0.5 mr-1" />}
                      {isDed ? "− " : isSubtotal ? "= " : ""}
                      {r.label}
                    </td>
                    <td
                      className={`py-1.5 text-right font-mono whitespace-nowrap ${
                        isSubtotal ? "font-semibold text-slate-900" : isDed ? "text-slate-500" : "text-slate-800"
                      }`}
                    >
                      {signedEur(r.value, r.kind)}
                    </td>
                    <td
                      className={`py-1.5 pl-3 text-right font-mono w-[60px] ${
                        isSubtotal ? "text-slate-600 font-semibold" : "text-slate-400"
                      }`}
                    >
                      {r.pctOfRevenue ?? ""}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-3 text-[10px] text-slate-400 italic">
            {hasRevenue
              ? "Tree reconciles to the filed EBITDA (rubric 9901 + 630). Any gap between raw rubrics and the filed subtotal lands in \u201Cother\u201D so the sum ties out."
              : "Revenue not disclosed (abbreviated-scheme filing). Tree starts at gross margin."}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
