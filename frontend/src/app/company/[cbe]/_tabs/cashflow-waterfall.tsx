"use client";

import React, { useMemo, useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import { fmtEur } from "@/lib/format";
import { deriveCashFlow, type RubricData, type CashFlowYear } from "@/lib/cashflow";

/**
 * Indirect-method cash-flow waterfall. Visual companion to the table below.
 * Both views read from the same derivation helper (`@/lib/cashflow`) so
 * the numbers always agree.
 *
 *   Net profit
 *     + D&A, write-downs, provisions
 *     − Exceptional income  + Exceptional charges
 *     ± ΔWorking capital              = Cash from Operations
 *                     − CapEx
 *                     ± Δ Financial FA = Cash from Investing
 *             ± Δ Debt  + New capital  − Dividends = Δ Cash (implied)
 *
 *   (Observed ΔCash from BS shown separately; gap row surfaces anything
 *   the model misses — M&A consolidation, FX, minority interest.)
 */

interface Props {
  rubrics: RubricData;
  fiscalYears: number[];
  defaultCollapsed?: boolean;
}

type Row = {
  label: string;
  value: number;
  startPct: number;
  endPct: number;
  kind: "milestone" | "deduction" | "addition";
  color: string;
  textColor: string;
  indent?: boolean;
};

export function CashFlowWaterfall({ rubrics, fiscalYears, defaultCollapsed = false }: Props) {
  const years = useMemo(
    () => [...new Set(fiscalYears)].filter((y) => typeof y === "number").sort((a, b) => a - b),
    [fiscalYears],
  );

  const [open, setOpen] = useState(!defaultCollapsed);
  const [fy, setFy] = useState<number | null>(() => (years.length ? years[years.length - 1] : null));

  React.useEffect(() => {
    if (years.length && (fy == null || !years.includes(fy))) {
      setFy(years[years.length - 1]);
    }
  }, [years, fy]);

  const derived = useMemo<CashFlowYear[]>(
    () => deriveCashFlow(rubrics, years),
    [rubrics, years],
  );

  const cf = useMemo(() => derived.find((r) => r.fiscalYear === fy) ?? null, [derived, fy]);

  if (!years.length || fy == null || !cf || cf.ebitda == null) return null;

  const isFirstYear = years[0] === fy;
  if (isFirstYear) return null;

  // Indirect-method bridge from EBITDA → CFO. interestExpense and
  // incomeTax are already signed as cash impact (negative for outflow).
  type FloatSpec = { label: string; delta: number };
  const opsFloats: FloatSpec[] = [
    { label: "+ Financial income", delta: cf.financialIncome },
    { label: cf.interestExpense <= 0 ? "− Interest paid" : "+ Interest refund", delta: cf.interestExpense },
    { label: cf.incomeTax <= 0 ? "− Income tax" : "+ Tax credit", delta: cf.incomeTax },
    { label: "+ Write-downs", delta: cf.writedowns },
    { label: "+ Provisions", delta: cf.provisions },
    { label: (cf.wcChange ?? 0) >= 0 ? "+ ΔWorking capital" : "− ΔWorking capital", delta: cf.wcChange ?? 0 },
  ].filter((f) => f.delta !== 0);

  const invFloats: FloatSpec[] = [
    { label: cf.capex != null && cf.capex >= 0 ? "+ Asset disposals" : "− CapEx", delta: cf.capex ?? 0 },
    { label: cf.changeInFinancialAssets != null && cf.changeInFinancialAssets >= 0 ? "+ Divestments" : "− Acquisitions", delta: cf.changeInFinancialAssets ?? 0 },
  ].filter((f) => f.delta !== 0);

  const finFloats: FloatSpec[] = [
    { label: cf.deltaLtDebt != null && cf.deltaLtDebt >= 0 ? "+ LT borrowings" : "− LT repayments", delta: cf.deltaLtDebt ?? 0 },
    { label: cf.deltaStDebt != null && cf.deltaStDebt >= 0 ? "+ ST borrowings" : "− ST repayments", delta: cf.deltaStDebt ?? 0 },
    { label: cf.newCapital != null && cf.newCapital >= 0 ? "+ New capital" : "− Capital return", delta: cf.newCapital ?? 0 },
    { label: "− Dividends", delta: cf.dividendsPaid },
  ].filter((f) => f.delta !== 0);

  // Domain — covers every milestone AND every running-balance extremum.
  const points: number[] = [0, cf.ebitda];
  {
    let running = cf.ebitda;
    for (const f of opsFloats) {
      running += f.delta;
      points.push(running);
    }
  }
  points.push(cf.cashFromOps ?? 0);
  points.push((cf.cashFromOps ?? 0) + (cf.cashFromInvesting ?? 0));
  points.push(cf.impliedCashChange ?? 0);
  {
    let running = (cf.cashFromOps ?? 0) + (cf.cashFromInvesting ?? 0);
    for (const f of finFloats) {
      running += f.delta;
      points.push(running);
    }
  }
  if (cf.observedCashChange != null) points.push(cf.observedCashChange);

  const domainMin = Math.min(...points);
  const domainMax = Math.max(...points);
  const domainRange = Math.max(1, domainMax - domainMin);
  const toPos = (v: number) => ((v - domainMin) / domainRange) * 100;
  const zeroPos = toPos(0);

  const COL = {
    milestone:   "bg-slate-300",
    milestoneTxt: "text-slate-700",
    milestoneStrong: "bg-slate-400",
    milestoneStrongTxt: "text-slate-800",
    posNet:     "bg-slate-500",
    posNetTxt:  "text-slate-900",
    negNet:     "bg-slate-300",
    negNetTxt:  "text-rose-700",
    addition:   "bg-slate-100",
    additionTxt: "text-slate-500",
    deduction:  "bg-slate-100",
    deductionTxt: "text-slate-500",
    observed:    "bg-slate-200",
    observedTxt: "text-slate-600",
  };

  const rows: Row[] = [];

  const pushMilestone = (label: string, v: number, color: string, posColor: string, negColor: string, textPos: string, textNeg: string) => {
    const startPct = Math.min(zeroPos, toPos(v));
    const endPct = Math.max(zeroPos, toPos(v));
    rows.push({
      label, value: v, kind: "milestone",
      startPct, endPct,
      color: v >= 0 ? (color || posColor) : negColor,
      textColor: v >= 0 ? textPos : textNeg,
    });
  };

  let running = cf.ebitda;
  const float = (label: string, delta: number) => {
    if (delta === 0) return;
    const before = running;
    running += delta;
    const lo = Math.min(before, running);
    const hi = Math.max(before, running);
    rows.push({
      label, value: delta,
      kind: delta > 0 ? "addition" : "deduction",
      startPct: toPos(lo),
      endPct: toPos(hi),
      color: delta > 0 ? COL.addition : COL.deduction,
      textColor: delta > 0 ? COL.additionTxt : COL.deductionTxt,
      indent: true,
    });
  };

  // Starting milestone: EBITDA, anchored at zero.
  pushMilestone("EBITDA", cf.ebitda,
                COL.milestone, COL.milestone, COL.negNet,
                COL.milestoneTxt, COL.negNetTxt);

  for (const f of opsFloats) float(f.label, f.delta);

  pushMilestone("Cash from Ops", cf.cashFromOps ?? 0,
                COL.milestone, COL.milestone, COL.negNet,
                COL.milestoneTxt, COL.negNetTxt);

  running = cf.cashFromOps ?? 0;
  for (const f of invFloats) float(f.label, f.delta);

  pushMilestone("Free cash flow", (cf.cashFromOps ?? 0) + (cf.cashFromInvesting ?? 0),
                COL.milestoneStrong, COL.milestoneStrong, COL.negNet,
                COL.milestoneStrongTxt, COL.negNetTxt);

  running = (cf.cashFromOps ?? 0) + (cf.cashFromInvesting ?? 0);
  for (const f of finFloats) float(f.label, f.delta);

  pushMilestone("Δ Cash (implied)", cf.impliedCashChange ?? 0,
                COL.posNet, COL.posNet, COL.negNet,
                COL.posNetTxt, COL.negNetTxt);

  if (cf.observedCashChange != null) {
    pushMilestone("Δ Cash (observed BS)", cf.observedCashChange,
                  COL.observed, COL.observed, COL.negNet,
                  COL.observedTxt, COL.negNetTxt);
  }

  const gap = cf.unreconciledGap;
  const gapRatio = cf.observedCashChange != null && gap != null
    ? Math.abs(gap) / Math.max(Math.abs(cf.observedCashChange), 1)
    : 0;
  const gapTone =
    gap == null
      ? "text-slate-400"
      : gapRatio > 0.05
        ? "text-rose-600 font-semibold"
        : gapRatio > 0.02
          ? "text-amber-600"
          : "text-slate-500";

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
            className="h-10 md:h-7 text-base md:text-[11px] border border-slate-200 rounded px-2 md:px-1.5 bg-white text-slate-600 hover:border-slate-300"
            aria-label="Fiscal year"
          >
            {[...years].reverse().map((y) => <option key={y} value={y}>FY{y}</option>)}
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
                  <div className={`w-[140px] md:w-[200px] shrink-0 truncate text-left ${
                    isMilestone ? `font-semibold ${r.textColor}` : r.textColor
                  } ${r.indent ? "pl-3 md:pl-5" : ""}`}>
                    {r.label}
                  </div>
                  <div className="flex-1 relative h-5 md:h-6 overflow-hidden">
                    <div
                      className="absolute top-0 bottom-0 w-px bg-slate-300"
                      style={{ left: `${zeroPos}%` }}
                    />
                    <div
                      className={`absolute top-0 h-full rounded ${r.color}`}
                      style={{ left: `${r.startPct}%`, width: `${width}%` }}
                    />
                  </div>
                  <div className={`w-[90px] md:w-[110px] shrink-0 text-right font-mono text-[11px] ${
                    isMilestone ? `font-semibold ${r.textColor}` : r.textColor
                  }`}>
                    {fmtEur(Math.abs(r.value))}
                  </div>
                </div>
              );
            })}
            {cf.observedCashChange != null && gap != null && (
              <div className="flex items-center gap-3 text-[11px] pt-2 mt-2 border-t border-dashed border-slate-200">
                <div className="w-[140px] md:w-[200px] shrink-0 text-left text-slate-500 pl-3 md:pl-5">
                  Unexplained gap
                </div>
                <div className="flex-1 text-[10px] text-slate-400">
                  observed − implied; large values suggest M&amp;A, FX or
                  items not modelled
                </div>
                <div className={`w-[90px] md:w-[110px] shrink-0 text-right font-mono ${gapTone}`}>
                  {fmtEur(gap)}
                </div>
              </div>
            )}
          </div>
          <p className="text-[10px] text-slate-400 italic mt-2">
            Indirect method from EBITDA. Adjusts for financial income /
            interest / tax, adds back non-cash items (write-downs,
            provisions), bridges working capital, then CapEx &amp; financing.
            Exceptional items never enter EBITDA, so no strip line is
            needed. Belgian GAAP does not file a cash-flow statement; all
            values are derived from the balance sheet and P&amp;L.
          </p>
        </div>
      )}
    </div>
  );
}
