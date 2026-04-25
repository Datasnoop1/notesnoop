"use client";

import React, { useMemo, useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import { fmtEur } from "@/lib/format";

/* True floating horizontal waterfall.
 *   - Milestones (Revenue / Gross margin / EBITDA / EBIT / Net profit) render
 *     as full bars anchored to 0, width = milestone value as % of the domain.
 *   - Deductions render as FLOATING bars between milestones: each sits at
 *     the running balance, showing exactly what was subtracted.
 *
 * When Revenue is missing (abbreviated-scheme filings), the waterfall
 * anchors on Gross margin instead of hiding entirely — otherwise companies
 * that can't legally disclose turnover show an empty panel.
 *
 * Belgian GAAP rubrics (match backend whitelist in companies/financials.py):
 *   70    Revenue
 *   60    Materials
 *   61    Services
 *   9900  Gross margin
 *   62    Personnel
 *   640/8 Other operating costs
 *   630   D&A
 *   9901  EBIT
 *   65    Financial charges
 *   67/77 Tax
 *   9904  Net profit
 */

interface Props {
  rubrics: Record<string, Record<string, number | null>>;
  fiscalYears: number[];
  defaultCollapsed?: boolean;
}

function rub(r: Record<string, Record<string, number | null>>, code: string, fy: number): number {
  const v = r?.[code]?.[String(fy)];
  return typeof v === "number" ? v : 0;
}

type Row = {
  label: string;
  value: number;          // absolute magnitude, used for bar-width math
  signed: number;         // original signed value, used only for display
  startPct: number;       // bar left edge (0..100)
  endPct: number;         // bar right edge (0..100)
  kind: "milestone" | "deduction";
  color: string;          // bar tailwind bg
  textColor: string;      // label text tailwind
  pctLabel?: string;      // inline % for milestones
  indent?: boolean;       // indent sub-category labels (deductions)
};

export function PnlWaterfall({ rubrics, fiscalYears, defaultCollapsed = false }: Props) {
  const years = useMemo(
    () => [...new Set(fiscalYears)].filter((y) => typeof y === "number").sort((a, b) => b - a),
    [fiscalYears],
  );

  const [open, setOpen] = useState(!defaultCollapsed);
  const [fy, setFy] = useState<number | null>(years[0] ?? null);

  // Re-sync fy when the parent's year list changes (e.g. financials load
  // in async after mount, or user switches company). Without this the
  // component would silently return null if initial fiscalYears was empty.
  React.useEffect(() => {
    if (years.length && (fy == null || !years.includes(fy))) {
      setFy(years[0]);
    }
  }, [years, fy]);

  if (!years.length || fy == null) return null;

  // Read milestones first — we need them to compute the domain below,
  // since any can go negative (EBITDA / EBIT / net profit for distressed
  // companies) and should render left of the zero line.

  const revenue = rub(rubrics, "70", fy);
  const materials = Math.max(0, rub(rubrics, "60", fy));
  const services = Math.max(0, rub(rubrics, "61", fy));
  const personnel = Math.max(0, rub(rubrics, "62", fy));
  const otherOp = Math.max(0, rub(rubrics, "640/8", fy));
  const da = Math.max(0, rub(rubrics, "630", fy));
  const ebit = rub(rubrics, "9901", fy);
  const ebitda = ebit + da;
  const finCharges = Math.max(0, rub(rubrics, "65", fy));
  const tax = Math.max(0, rub(rubrics, "67/77", fy));
  const netProfit = rub(rubrics, "9904", fy);
  // Gross margin — ONLY when rubric 9900 is explicitly reported. The
  // earlier fallback (revenue - materials - services) silently lied for
  // retailers and others where rubric 60 is cost-of-goods-sold and 61 is
  // operating services, not both part of cost-of-sales. Better to omit
  // the milestone than show a wrong number; the full P&L table still
  // surfaces every rubric honestly.
  const rawGm = rub(rubrics, "9900", fy);
  const hasGrossMarginMilestone = rawGm > 0;
  const grossMargin = rawGm;

  // If neither revenue nor gross margin is usable, we can't anchor the
  // bars — hide the waterfall. When revenue is missing but GM 9900 is
  // present (abbreviated-scheme filers), anchor on GM so the rest of
  // the bridge still renders (#9).
  const hasRevenue = revenue > 0;
  if (!hasRevenue && !hasGrossMarginMilestone) return null;

  // Anchor: prefer revenue; else gross margin.
  const topValue = hasRevenue ? revenue : grossMargin;

  // Domain includes the anchor, the zero line, and every milestone so
  // negative EBIT/EBITDA/net profit render left of zero without clipping.
  const domainPoints = [0, topValue, ebitda, ebit, netProfit];
  if (hasGrossMarginMilestone) domainPoints.push(grossMargin);
  const domainMin = Math.min(...domainPoints);
  const domainMax = Math.max(...domainPoints);
  const domainRange = Math.max(1, domainMax - domainMin);
  const toPos = (v: number) => ((v - domainMin) / domainRange) * 100;
  const zeroPos = toPos(0);

  // Palette: shades of gray only. Milestones get progressively darker as
  // the journey from top line to bottom line progresses; deductions stay
  // lightest. Negative bottom-line gets a muted gray too, with red
  // reserved for text when net is negative (so the chart stays quiet).
  const COL = {
    revenue:    "bg-slate-300",
    revenueTxt: "text-slate-700",
    // Gross margin sits between the revenue band and EBITDA: slightly darker
    // than revenue so it reads as a distinct waypoint.
    grossMargin: "bg-slate-400",
    grossMarginTxt: "text-slate-800",
    milestone:  "bg-slate-300",
    milestoneTxt: "text-slate-700",
    milestoneStrong: "bg-slate-400",
    milestoneStrongTxt: "text-slate-800",
    netPos:     "bg-slate-500",
    netPosTxt:  "text-slate-900",
    netNeg:     "bg-slate-300",
    netNegTxt:  "text-rose-700",
    deduction:  "bg-slate-100",
    deductionTxt: "text-slate-500",
  };

  // Waterfall math — the deductions MUST tie out to the next milestone so
  // the floating bars form a continuous staircase with no gaps.
  //
  // Between Revenue and EBITDA the total drop is `revenue - ebitda`. We
  // show it split across the rubric breakdown (Materials / Services /
  // Personnel / Other). Any gap between the sum of those rubrics and the
  // true total lands in the "Other OpEx" residual so the staircase lands
  // exactly at the EBITDA milestone.
  //
  // Same pattern between EBIT and Net profit: total = ebit - netProfit
  // split across Fin charges + Tax + residual (shown as "Other").
  const rows: Row[] = [];

  // Milestone bar anchored at zero: extends right for positive, left for
  // negative. Takes care of negative EBIT / EBITDA / net profit cleanly.
  const pushMilestone = (label: string, v: number, color: string, textColor: string, pctLabel?: string) => {
    rows.push({
      label, value: Math.abs(v), kind: "milestone",
      startPct: Math.min(zeroPos, toPos(v)),
      endPct: Math.max(zeroPos, toPos(v)),
      color, textColor,
      pctLabel,
      // Preserve sign for display — the bar uses abs for width but the
      // row label should read as negative when the underlying milestone
      // is negative.
      signed: v,
    });
  };
  // Floating bar between two running-balance positions. Bar always drawn
  // left→right regardless of whether `running` increased or decreased.
  const pushBar = (label: string, fromVal: number, toVal: number) => {
    const lo = Math.min(fromVal, toVal);
    const hi = Math.max(fromVal, toVal);
    rows.push({
      label, value: Math.abs(toVal - fromVal),
      kind: "deduction",
      startPct: toPos(lo),
      endPct: toPos(hi),
      color: COL.deduction, textColor: COL.deductionTxt,
      indent: true,
      // Signed delta for the display row (+ for add-backs, − for costs);
      // the bar width stays positive.
      signed: toVal - fromVal,
    });
  };

  // Waterfall phases — branching on whether we have a filed Gross Margin
  // milestone. Without 9900, we revert to the original Revenue→EBITDA
  // bridge so we never show a derived GM that might be wrong.
  let running: number;
  if (hasRevenue && hasGrossMarginMilestone) {
    // === Revenue → Gross margin → EBITDA ===
    pushMilestone("Revenue", revenue, COL.revenue, COL.revenueTxt, "100.0%");
    running = revenue;
    const totalCos = revenue - grossMargin;
    const knownCos = materials + services;
    const cosUnder = Math.max(0, totalCos - knownCos);
    const cosOver = Math.max(0, knownCos - totalCos);
    const pushDed = (label: string, v: number) => {
      if (v <= 0) return;
      const before = running;
      running -= v;
      pushBar(label, before, running);
    };
    pushDed("Materials", materials);
    pushDed("Services", services);
    if (cosUnder > 0) pushDed("Other cost of sales", cosUnder);
    if (cosOver > 0) {
      const before = running;
      running += cosOver;
      pushBar("Other revenue", before, running);
    }
    pushMilestone(
      "Gross margin",
      grossMargin,
      COL.grossMargin,
      COL.grossMarginTxt,
      `${(grossMargin / revenue * 100).toFixed(1)}%`,
    );
    running = grossMargin;
    const totalGmToEbitda = grossMargin - ebitda;
    const knownGmToEbitda = personnel + otherOp;
    const gmUnder = Math.max(0, totalGmToEbitda - knownGmToEbitda);
    const gmOver = Math.max(0, knownGmToEbitda - totalGmToEbitda);
    const pushGmDed = (label: string, v: number) => {
      if (v <= 0) return;
      const before = running;
      running -= v;
      pushBar(label, before, running);
    };
    pushGmDed("Personnel", personnel);
    pushGmDed("Other OpEx", otherOp + gmUnder);
    if (gmOver > 0) {
      const before = running;
      running += gmOver;
      pushBar("Other op income", before, running);
    }
  } else if (!hasRevenue && hasGrossMarginMilestone) {
    // === Abbreviated-scheme filer (#9): anchor on Gross margin ===
    pushMilestone("Gross margin", grossMargin, COL.grossMargin, COL.grossMarginTxt, undefined);
    running = grossMargin;
    const totalGmToEbitda = grossMargin - ebitda;
    const knownGmToEbitda = personnel + otherOp;
    const gmUnder = Math.max(0, totalGmToEbitda - knownGmToEbitda);
    const gmOver = Math.max(0, knownGmToEbitda - totalGmToEbitda);
    const pushGmDed = (label: string, v: number) => {
      if (v <= 0) return;
      const before = running;
      running -= v;
      pushBar(label, before, running);
    };
    pushGmDed("Personnel", personnel);
    pushGmDed("Other OpEx", otherOp + gmUnder);
    if (gmOver > 0) {
      const before = running;
      running += gmOver;
      pushBar("Other op income", before, running);
    }
  } else {
    // === No filed Gross margin: original Revenue → EBITDA bridge ===
    pushMilestone("Revenue", revenue, COL.revenue, COL.revenueTxt, "100.0%");
    running = revenue;
    const totalOpex = revenue - ebitda;
    const knownOpex = materials + services + personnel + otherOp;
    const opexUnder = Math.max(0, totalOpex - knownOpex);
    const opexOver = Math.max(0, knownOpex - totalOpex);
    const pushDed = (label: string, v: number) => {
      if (v <= 0) return;
      const before = running;
      running -= v;
      pushBar(label, before, running);
    };
    pushDed("Materials", materials);
    pushDed("Services", services);
    pushDed("Personnel", personnel);
    pushDed("Other OpEx", otherOp + opexUnder);
    if (opexOver > 0) {
      const before = running;
      running += opexOver;
      pushBar("Other op income", before, running);
    }
  }

  pushMilestone("EBITDA", ebitda, COL.milestone, COL.milestoneTxt,
                hasRevenue ? `${(ebitda / revenue * 100).toFixed(1)}%` : undefined);

  // D&A bridges EBITDA → EBIT (positive D&A only; skip if zero/negative).
  if (Math.abs(ebitda - ebit) > 0.01) pushBar("D&A", ebitda, ebit);

  pushMilestone("EBIT", ebit, COL.milestoneStrong, COL.milestoneStrongTxt,
                revenue > 0 ? `${(ebit / revenue * 100).toFixed(1)}%` : undefined);

  // Between EBIT and Net profit: same bidirectional reconciliation.
  const totalBelowEbit = ebit - netProfit;
  const knownBelowEbit = finCharges + tax;
  const belowUnder = Math.max(0, totalBelowEbit - knownBelowEbit);
  const belowOver  = Math.max(0, knownBelowEbit - totalBelowEbit);

  let ebitRunning = ebit;
  const pushBelowEbit = (label: string, v: number) => {
    if (v <= 0) return;
    const before = ebitRunning;
    ebitRunning -= v;
    pushBar(label, before, ebitRunning);
  };
  const pushBelowAdd = (label: string, v: number) => {
    if (v <= 0) return;
    const before = ebitRunning;
    ebitRunning += v;
    pushBar(label, before, ebitRunning);
  };
  pushBelowEbit("Fin. charges", finCharges);
  pushBelowEbit("Tax",          tax);
  if (belowUnder > 0) pushBelowEbit("Other", belowUnder);
  if (belowOver > 0)  pushBelowAdd("Other financial income", belowOver);

  pushMilestone("Net profit", netProfit,
                netProfit >= 0 ? COL.netPos : COL.netNeg,
                netProfit >= 0 ? COL.netPosTxt : COL.netNegTxt,
                revenue > 0 ? `${(netProfit / revenue * 100).toFixed(1)}%` : undefined);

  return (
    <div className="rounded-lg border bg-white">
      {/* Header row — two siblings inside a flex, NOT nested interactive
          elements. */}
      <div className="flex items-center justify-between px-3 py-2">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 hover:bg-slate-50 -mx-1 px-1 py-0.5 rounded transition-colors"
          aria-expanded={open}
        >
          {open ? <ChevronDown className="h-3.5 w-3.5 text-slate-400" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-400" />}
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
            P&amp;L waterfall
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
                  {/* Milestones flush-left, sub-categories indented via pl —
                      matches the P&L table convention (main items outdented,
                      line items indented). */}
                  <div className={`w-[110px] md:w-[140px] shrink-0 truncate text-left ${
                    isMilestone ? `font-semibold ${r.textColor}` : r.textColor
                  } ${r.indent ? "pl-3 md:pl-5" : ""}`}>
                    {r.label}
                  </div>
                  <div className="flex-1 relative h-5 md:h-6 overflow-hidden">
                    {/* Zero-reference line — shows whether bars sit left
                        (negative) or right (positive) of the zero axis. */}
                    <div
                      className="absolute top-0 bottom-0 w-px bg-slate-300"
                      style={{ left: `${zeroPos}%` }}
                    />
                    <div
                      className={`absolute top-0 h-full rounded ${r.color}`}
                      style={{ left: `${r.startPct}%`, width: `${width}%` }}
                    />
                    {isMilestone && r.pctLabel && (
                      <span
                        className="absolute top-0 h-full flex items-center text-[10px] text-slate-700 font-mono font-semibold"
                        style={{ left: `calc(${Math.min(96, r.endPct)}% + 2px)` }}
                      >
                        {r.pctLabel}
                      </span>
                    )}
                  </div>
                  <div className={`w-[90px] md:w-[110px] shrink-0 text-right font-mono text-[11px] ${
                    isMilestone ? `font-semibold ${r.textColor}` : r.textColor
                  }`}>
                    {/* Milestones are balances — fmtEur(signed) natively
                        shows "-" for negative EBIT/EBITDA/net profit.
                        Flows are always signed: "+" for add-backs (Other
                        op income), "−" for cost deductions. */}
                    {isMilestone
                      ? fmtEur(r.signed)
                      : (r.signed >= 0 ? `+${fmtEur(r.value)}` : `\u2212${fmtEur(r.value)}`)}
                  </div>
                </div>
              );
            })}
          </div>
          <p className="text-[10px] text-slate-400 italic mt-2">
            True floating waterfall — deductions sit at the running balance
            between milestones. Bars scaled to Revenue (100%).
          </p>
        </div>
      )}
    </div>
  );
}
