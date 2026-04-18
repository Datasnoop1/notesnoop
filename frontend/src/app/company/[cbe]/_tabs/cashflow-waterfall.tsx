"use client";

import React, { useMemo, useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import { fmtEur } from "@/lib/format";

/* True floating cash-flow waterfall.
 *
 *   Net profit + D&A ± ΔWorking capital = Operating CF
 *              − CapEx                  = Free cash flow
 *              ± Net debt movement      = Δ Cash
 *
 * Milestones render anchored to 0, widths in % of the largest absolute
 * flow so every row is visible. Deductions + additions float between
 * milestones at the running balance, so it reads like a proper
 * accounting bridge.
 *
 * Rubric codes match what companies/financials.py emits (3 = inventories,
 * 41 = receivables, 44 = trade payables, 20/28 = total fixed assets,
 * 17 = LT debt, 43 = ST fin debt).
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
  startPct: number;
  endPct: number;
  kind: "milestone" | "deduction" | "addition";
  color: string;
  textColor: string;
};

export function CashFlowWaterfall({ rubrics, fiscalYears, defaultCollapsed = false }: Props) {
  const years = useMemo(
    () => [...new Set(fiscalYears)].filter((y) => typeof y === "number").sort((a, b) => b - a),
    [fiscalYears],
  );

  const [open, setOpen] = useState(!defaultCollapsed);
  const [fy, setFy] = useState<number | null>(years[0] ?? null);

  if (!years.length || fy == null) return null;

  const prevFy = years.find((y) => y < fy) ?? null;

  const netProfit = rub(rubrics, "9904", fy);
  const da = Math.max(0, rub(rubrics, "630", fy));

  const receivablesChange = rub(rubrics, "41", fy) - rub(rubrics, "41", prevFy);
  const inventoriesChange = rub(rubrics, "3", fy) - rub(rubrics, "3", prevFy);
  const payablesChange = rub(rubrics, "44", fy) - rub(rubrics, "44", prevFy);
  const wcChange = receivablesChange + inventoriesChange - payablesChange;

  const grossFaThis = rub(rubrics, "20/28", fy);
  const grossFaPrev = rub(rubrics, "20/28", prevFy);
  const capex = prevFy ? Math.max(0, grossFaThis - grossFaPrev + da) : 0;

  const debtThis = rub(rubrics, "17", fy) + rub(rubrics, "43", fy);
  const debtPrev = rub(rubrics, "17", prevFy) + rub(rubrics, "43", prevFy);
  const debtMovement = prevFy ? (debtThis - debtPrev) : 0;

  // Milestones
  const operatingCf = netProfit + da - wcChange;
  const fcf = operatingCf - capex;
  const changeInCash = fcf + debtMovement;

  // Scale: biggest absolute flow gives 100%. This keeps even small
  // deductions visible — unlike scaling to revenue where they'd vanish.
  const scaleBase = Math.max(
    1,
    Math.abs(netProfit) + Math.max(0, da) + Math.max(0, -wcChange) + Math.max(0, wcChange),
    Math.abs(operatingCf),
    Math.abs(operatingCf) + capex,
    Math.abs(fcf) + Math.abs(debtMovement),
    Math.abs(changeInCash),
  );
  const toPct = (v: number) => (v / scaleBase) * 100;

  const rows: Row[] = [];

  // Starting point: Net profit milestone (anchored to 0)
  {
    const end = Math.max(0, Math.abs(netProfit));
    rows.push({
      label: "Net profit", value: Math.abs(netProfit), kind: "milestone",
      startPct: 0, endPct: Math.min(100, toPct(end)),
      color: netProfit >= 0 ? "bg-emerald-300" : "bg-rose-300",
      textColor: netProfit >= 0 ? "text-emerald-700" : "text-rose-700",
    });
  }

  // Build cumulative from Net profit up to Operating CF, then down through
  // CapEx to FCF, then ± debt to Δ Cash. Each floating bar bridges two
  // consecutive cumulative positions.
  let running = netProfit;
  const float = (label: string, delta: number, color: string, textColor: string) => {
    if (delta === 0) return;
    const before = running;
    running += delta;
    const lo = Math.min(before, running);
    const hi = Math.max(before, running);
    rows.push({
      label, value: Math.abs(delta),
      kind: delta > 0 ? "addition" : "deduction",
      startPct: toPct(Math.max(0, lo)),
      endPct: toPct(Math.max(0, hi)),
      color, textColor,
    });
  };

  if (da > 0)               float("+ D&A",           +da,        "bg-emerald-200", "text-emerald-600");
  if (prevFy && wcChange !== 0) {
    const isUse = wcChange > 0;                 // WC grew → cash use
    float(isUse ? "− ΔWorking cap" : "+ ΔWorking cap",
          -wcChange,
          isUse ? "bg-rose-200" : "bg-emerald-200",
          isUse ? "text-rose-600" : "text-emerald-600");
  }

  // Operating CF milestone
  rows.push({
    label: "Operating CF", value: Math.abs(operatingCf), kind: "milestone",
    startPct: 0, endPct: Math.min(100, toPct(Math.max(0, Math.abs(operatingCf)))),
    color: operatingCf >= 0 ? "bg-emerald-300" : "bg-rose-300",
    textColor: operatingCf >= 0 ? "text-emerald-700" : "text-rose-700",
  });

  // Reset running to operatingCf (for the CapEx bridge)
  running = operatingCf;
  if (prevFy && capex > 0) float("− CapEx", -capex, "bg-amber-200", "text-amber-600");

  // FCF milestone
  rows.push({
    label: "Free cash flow", value: Math.abs(fcf), kind: "milestone",
    startPct: 0, endPct: Math.min(100, toPct(Math.max(0, Math.abs(fcf)))),
    color: fcf >= 0 ? "bg-emerald-400" : "bg-rose-400",
    textColor: fcf >= 0 ? "text-emerald-800" : "text-rose-700",
  });

  // Reset running to fcf (for the debt bridge)
  running = fcf;
  if (prevFy && debtMovement !== 0) {
    const isBorrow = debtMovement > 0;
    float(isBorrow ? "+ Net borrowings" : "− Net debt repay",
          debtMovement,
          isBorrow ? "bg-indigo-200" : "bg-rose-200",
          isBorrow ? "text-indigo-600" : "text-rose-600");
  }

  // Δ Cash milestone
  rows.push({
    label: "Δ Cash", value: Math.abs(changeInCash), kind: "milestone",
    startPct: 0, endPct: Math.min(100, toPct(Math.max(0, Math.abs(changeInCash)))),
    color: changeInCash >= 0 ? "bg-emerald-400" : "bg-rose-400",
    textColor: changeInCash >= 0 ? "text-emerald-800" : "text-rose-700",
  });

  return (
    <div className="rounded-lg border bg-white">
      <div className="flex items-center justify-between px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 hover:bg-slate-50 -mx-1 px-1 py-0.5 rounded transition-colors"
          aria-expanded={open}
        >
          {open ? <ChevronDown className="h-3.5 w-3.5 text-slate-400" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-400" />}
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
            Cash-flow waterfall
          </h3>
          <span className="text-[10px] text-slate-400">— FY{fy}</span>
        </button>
        {years.length > 1 && (
          <select
            value={fy}
            onChange={(e) => setFy(Number(e.target.value))}
            className="text-[11px] border border-slate-200 rounded px-1.5 py-0.5 bg-white text-slate-600 hover:border-slate-300"
            aria-label="Fiscal year"
          >
            {years.map((y) => <option key={y} value={y}>FY{y}</option>)}
          </select>
        )}
      </div>
      {open && (
        <div className="px-3 pb-3 pt-1 border-t border-slate-100">
          <div className="space-y-1">
            {rows.map((r, i) => {
              const width = Math.max(0.5, r.endPct - r.startPct);
              const isMilestone = r.kind === "milestone";
              return (
                <div key={`${i}-${r.label}`} className="flex items-center gap-3 text-[12px]">
                  <div className={`w-[120px] md:w-[150px] shrink-0 text-right truncate ${
                    isMilestone ? `font-semibold ${r.textColor}` : r.textColor
                  }`}>
                    {r.label}
                  </div>
                  <div className="flex-1 relative h-5 md:h-6 bg-slate-50 rounded overflow-hidden">
                    <div
                      className={`absolute top-0 h-full rounded ${r.color}`}
                      style={{ left: `${r.startPct}%`, width: `${width}%` }}
                    />
                  </div>
                  <div className={`w-[90px] md:w-[110px] shrink-0 text-right font-mono text-[11px] ${
                    isMilestone ? `font-semibold ${r.textColor}` : r.textColor
                  }`}>
                    {fmtEur(r.value)}
                  </div>
                </div>
              );
            })}
          </div>
          <p className="text-[10px] text-slate-400 italic mt-2">
            Indirect method. Floating bars sit at the running balance
            between milestones. Bars scaled to the largest absolute flow.
          </p>
        </div>
      )}
    </div>
  );
}
