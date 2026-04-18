"use client";

import React from "react";
import { fmtEur } from "@/lib/format";

/* Waterfall-style P&L diagram: Revenue → EBITDA → EBIT → Net profit.
 * Each step shows the metric value as a solid bar and the deductions
 * between steps as shorter grey bars. Proportional, colour-coded, and
 * readable at any viewport width. No external dep.
 *
 * Belgian GAAP rubric mapping:
 *   70           Revenue
 *   60+61+62+640 Operating cost buckets (materials + services + personnel + other)
 *   630          Depreciation & amortisation
 *   9901         Operating profit (EBIT)
 *   65           Financial charges
 *   67           Tax
 *   9904         Net profit
 */

interface Props {
  rubrics: Record<string, Record<string, number | null>>;
  fiscalYear: number;
}

function rub(r: Record<string, Record<string, number | null>>, code: string, fy: number): number {
  const v = r?.[code]?.[String(fy)];
  return typeof v === "number" ? v : 0;
}

export function PnlWaterfall({ rubrics, fiscalYear }: Props) {
  const revenue = rub(rubrics, "70", fiscalYear);
  if (revenue <= 0) return null;

  // Derived milestones — prefer pre-computed rubrics when present; fall back
  // to computed values so the chart is usable even for partial filings.
  const materials = Math.max(0, rub(rubrics, "60", fiscalYear) + rub(rubrics, "61", fiscalYear));
  const personnel = Math.max(0, rub(rubrics, "62", fiscalYear));
  const da = Math.max(0, rub(rubrics, "630", fiscalYear));
  const otherOp = Math.max(0, rub(rubrics, "640", fiscalYear));
  const operatingExp = materials + personnel + otherOp;

  const ebit = rub(rubrics, "9901", fiscalYear);
  // EBITDA = EBIT + D&A (standard Belgian GAAP derivation per docs/belgian-gaap.md)
  const ebitda = ebit + da;

  const finCharges = Math.max(0, rub(rubrics, "65", fiscalYear));
  const tax = Math.max(0, rub(rubrics, "67", fiscalYear));
  const netProfit = rub(rubrics, "9904", fiscalYear);

  // Layout — vertical waterfall. Each row has a label cell, a bar area, and
  // a value cell. Bars share the same horizontal scale (% of revenue).
  type Row = {
    label: string;
    value: number;
    kind: "milestone" | "deduction";
    color: string;
    pct?: number;        // margin vs revenue
  };
  const rows: Row[] = [
    { label: "Revenue",            value: revenue,      kind: "milestone", color: "#6366f1" },
  ];
  if (operatingExp > 0) {
    rows.push({ label: "− Operating costs", value: operatingExp, kind: "deduction", color: "#ef4444" });
  }
  rows.push({
    label: "EBITDA",
    value: Math.max(0, ebitda),
    kind: "milestone",
    color: "#10b981",
    pct: revenue > 0 ? (ebitda / revenue) * 100 : undefined,
  });
  if (da > 0) {
    rows.push({ label: "− D&A", value: da, kind: "deduction", color: "#f97316" });
  }
  rows.push({
    label: "EBIT",
    value: Math.max(0, ebit),
    kind: "milestone",
    color: "#059669",
    pct: revenue > 0 ? (ebit / revenue) * 100 : undefined,
  });
  if (finCharges > 0) {
    rows.push({ label: "− Financial charges", value: finCharges, kind: "deduction", color: "#dc2626" });
  }
  if (tax > 0) {
    rows.push({ label: "− Tax", value: tax, kind: "deduction", color: "#78716c" });
  }
  rows.push({
    label: "Net profit",
    value: Math.max(0, netProfit),
    kind: "milestone",
    color: netProfit >= 0 ? "#065f46" : "#be123c",
    pct: revenue > 0 ? (netProfit / revenue) * 100 : undefined,
  });

  const maxBar = revenue;

  return (
    <div className="rounded-lg border bg-white p-3 md:p-4">
      <div className="flex items-baseline justify-between mb-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 border-l-[3px] border-indigo-500 pl-2">
          P&amp;L waterfall — FY{fiscalYear}
        </h3>
        <span className="text-[10px] text-slate-400">revenue 100%</span>
      </div>
      <div className="space-y-1.5">
        {rows.map((r, i) => {
          const pct = maxBar > 0 ? Math.min(100, (r.value / maxBar) * 100) : 0;
          const isMilestone = r.kind === "milestone";
          return (
            <div key={`${i}-${r.label}`} className="flex items-center gap-3 text-[12px]">
              <div className={`w-[110px] md:w-[140px] shrink-0 text-right truncate ${
                isMilestone ? "font-semibold text-slate-700" : "text-slate-500"
              }`}>
                {r.label}
              </div>
              <div className="flex-1 relative h-5 md:h-6 bg-slate-50 rounded overflow-hidden">
                <div
                  className="absolute left-0 top-0 h-full rounded transition-all"
                  style={{
                    width: `${pct}%`,
                    backgroundColor: r.color,
                    opacity: isMilestone ? 0.88 : 0.65,
                  }}
                />
                {r.pct != null && (
                  <span className="absolute right-1.5 top-0 h-full flex items-center text-[10px] text-white font-mono font-semibold drop-shadow">
                    {r.pct.toFixed(1)}%
                  </span>
                )}
              </div>
              <div className={`w-[90px] md:w-[110px] shrink-0 text-right font-mono text-[11px] ${
                isMilestone ? "text-slate-800 font-semibold" : "text-slate-500"
              }`}>
                {fmtEur(r.value)}
              </div>
            </div>
          );
        })}
      </div>
      <p className="text-[10px] text-slate-400 italic mt-2">
        Bars scaled to revenue. Milestones (Revenue / EBITDA / EBIT / Net profit) show margin %.
      </p>
    </div>
  );
}
