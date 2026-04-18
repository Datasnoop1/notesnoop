"use client";

import React, { useMemo, useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import { fmtEur } from "@/lib/format";

/* Cash-flow waterfall: derived from rubrics + period-over-period deltas.
 * Net profit → + D&A → − ΔWorking capital → = Operating CF → − CapEx
 * → = Free cash flow → ± Net debt movement → = Change in cash.
 *
 * Belgian GAAP rubrics used:
 *   9904     Net profit
 *   630      D&A (added back — non-cash)
 *   29       LT trade receivables
 *   40/41    Trade + other receivables  (we approximate with rubric 40)
 *   30       Inventories
 *   44       Trade payables
 *   22-27    Tangible + intangible fixed assets (sum for CapEx proxy)
 *   17       LT debt (for net debt movement)
 *   43       ST fin. debt
 *
 * CapEx is approximated as: (gross fixed assets this year − last year) + D&A.
 * ΔWorking capital = Δreceivables + Δinventories − Δpayables.
 * Pure SVG/CSS, no dep.
 */

interface Props {
  rubrics: Record<string, Record<string, number | null>>;
  fiscalYears: number[];
  defaultCollapsed?: boolean;
}

function rub(r: Record<string, Record<string, number | null>>, code: string, fy: number | null): number {
  if (fy == null) return 0;
  const v = r?.[code]?.[String(fy)];
  return typeof v === "number" ? v : 0;
}

type Row = {
  label: string;
  value: number;
  kind: "milestone" | "deduction" | "addition";
  color: string;
  bar: string;
  pct?: number;  // vs revenue when we have it
};

export function CashFlowWaterfall({ rubrics, fiscalYears, defaultCollapsed = true }: Props) {
  const years = useMemo(
    () => [...new Set(fiscalYears)].filter((y) => typeof y === "number").sort((a, b) => b - a),
    [fiscalYears],
  );

  const [open, setOpen] = useState(!defaultCollapsed);
  const [fy, setFy] = useState<number | null>(years[0] ?? null);

  if (!years.length || fy == null) return null;

  // Prior-year lookup for WC + CapEx deltas. Pick the next-older year that
  // actually exists in rubric_data. If there's no prior year, we skip the
  // delta-dependent rows rather than showing bogus zeros.
  const prevFy = years.find((y) => y < fy) ?? null;

  const netProfit = rub(rubrics, "9904", fy);
  const da = Math.max(0, rub(rubrics, "630", fy));

  // Working capital change (positive when WC grows → cash use → subtracts)
  const receivablesChange = rub(rubrics, "40", fy) - rub(rubrics, "40", prevFy);
  const inventoriesChange = rub(rubrics, "30", fy) - rub(rubrics, "30", prevFy);
  const payablesChange = rub(rubrics, "44", fy) - rub(rubrics, "44", prevFy);
  const wcChange = receivablesChange + inventoriesChange - payablesChange;

  // Gross fixed-assets delta + D&A ≈ CapEx
  const grossFaThis = rub(rubrics, "22", fy) + rub(rubrics, "23", fy) + rub(rubrics, "24", fy) +
                      rub(rubrics, "25", fy) + rub(rubrics, "27", fy);
  const grossFaPrev = rub(rubrics, "22", prevFy) + rub(rubrics, "23", prevFy) + rub(rubrics, "24", prevFy) +
                      rub(rubrics, "25", prevFy) + rub(rubrics, "27", prevFy);
  const capex = prevFy ? Math.max(0, grossFaThis - grossFaPrev + da) : 0;

  // Net debt movement: Δ(LT + ST fin debt). Positive = new borrowings = cash in.
  const debtThis = rub(rubrics, "17", fy) + rub(rubrics, "43", fy);
  const debtPrev = rub(rubrics, "17", prevFy) + rub(rubrics, "43", prevFy);
  const debtMovement = prevFy ? (debtThis - debtPrev) : 0;

  // Milestones
  const operatingCf = netProfit + da - wcChange;
  const fcf = operatingCf - capex;
  const changeInCash = fcf + debtMovement;

  const rows: Row[] = [
    {
      label: "Net profit", value: Math.abs(netProfit), kind: "milestone",
      color: netProfit >= 0 ? "text-emerald-700" : "text-rose-700",
      bar: netProfit >= 0 ? "bg-emerald-300" : "bg-rose-300",
    },
  ];
  if (da > 0) rows.push({ label: "+ D&A", value: da, kind: "addition", color: "text-emerald-600", bar: "bg-emerald-200" });

  if (prevFy && wcChange !== 0) {
    const incr = wcChange > 0;                       // WC grew → cash out → red
    rows.push({
      label: incr ? "− ΔWorking cap" : "+ ΔWorking cap",
      value: Math.abs(wcChange),
      kind: incr ? "deduction" : "addition",
      color: incr ? "text-rose-600" : "text-emerald-600",
      bar: incr ? "bg-rose-200" : "bg-emerald-200",
    });
  }

  rows.push({
    label: "Operating CF", value: Math.abs(operatingCf), kind: "milestone",
    color: operatingCf >= 0 ? "text-emerald-800" : "text-rose-700",
    bar: operatingCf >= 0 ? "bg-emerald-300" : "bg-rose-300",
  });

  if (prevFy && capex > 0) {
    rows.push({ label: "− CapEx", value: capex, kind: "deduction", color: "text-amber-600", bar: "bg-amber-200" });
  }

  rows.push({
    label: "Free cash flow", value: Math.abs(fcf), kind: "milestone",
    color: fcf >= 0 ? "text-emerald-800" : "text-rose-700",
    bar: fcf >= 0 ? "bg-emerald-400" : "bg-rose-400",
  });

  if (prevFy && debtMovement !== 0) {
    const borrow = debtMovement > 0;
    rows.push({
      label: borrow ? "+ Net borrowings" : "− Net debt repay",
      value: Math.abs(debtMovement),
      kind: borrow ? "addition" : "deduction",
      color: borrow ? "text-indigo-600" : "text-rose-600",
      bar: borrow ? "bg-indigo-200" : "bg-rose-200",
    });
  }

  rows.push({
    label: "Δ Cash", value: Math.abs(changeInCash), kind: "milestone",
    color: changeInCash >= 0 ? "text-emerald-800" : "text-rose-700",
    bar: changeInCash >= 0 ? "bg-emerald-400" : "bg-rose-400",
  });

  // Bars scaled to the biggest absolute milestone (Net profit or OperatingCF
  // — whichever is larger), so deduction bars stay visible even when the
  // final Δcash is small.
  const maxBar = Math.max(
    1,
    Math.abs(netProfit),
    Math.abs(operatingCf),
    Math.abs(fcf),
    Math.abs(changeInCash),
    da, capex, Math.abs(wcChange), Math.abs(debtMovement),
  );

  return (
    <div className="rounded-lg border bg-white">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          {open ? <ChevronDown className="h-3.5 w-3.5 text-slate-400" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-400" />}
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
            Cash-flow waterfall
          </h3>
          <span className="text-[10px] text-slate-400">— FY{fy}</span>
        </div>
        {years.length > 1 && (
          <select
            value={fy}
            onChange={(e) => setFy(Number(e.target.value))}
            onClick={(e) => e.stopPropagation()}
            className="text-[11px] border border-slate-200 rounded px-1.5 py-0.5 bg-white text-slate-600 hover:border-slate-300"
          >
            {years.map((y) => <option key={y} value={y}>FY{y}</option>)}
          </select>
        )}
      </button>
      {open && (
        <div className="px-3 pb-3 pt-1 border-t border-slate-100">
          <div className="space-y-1">
            {rows.map((r, i) => {
              const pct = maxBar > 0 ? Math.min(100, (r.value / maxBar) * 100) : 0;
              const isMilestone = r.kind === "milestone";
              return (
                <div key={`${i}-${r.label}`} className="flex items-center gap-3 text-[12px]">
                  <div className={`w-[120px] md:w-[150px] shrink-0 text-right truncate ${
                    isMilestone ? `font-semibold ${r.color}` : "text-slate-500"
                  }`}>
                    {r.label}
                  </div>
                  <div className="flex-1 relative h-5 md:h-6 bg-slate-50 rounded overflow-hidden">
                    <div
                      className={`absolute left-0 top-0 h-full rounded ${r.bar}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className={`w-[90px] md:w-[110px] shrink-0 text-right font-mono text-[11px] ${
                    isMilestone ? `font-semibold ${r.color}` : "text-slate-500"
                  }`}>
                    {fmtEur(r.value)}
                  </div>
                </div>
              );
            })}
          </div>
          <p className="text-[10px] text-slate-400 italic mt-2">
            Indirect method. Working-capital Δ, CapEx and debt movement require
            a prior year to compute — shown only when FY{prevFy ?? "—"} data is
            available. Bars scaled to the largest absolute flow.
          </p>
        </div>
      )}
    </div>
  );
}
