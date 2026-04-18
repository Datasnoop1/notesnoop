"use client";

import React, { useMemo, useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import { fmtEur } from "@/lib/format";

/* True floating horizontal waterfall.
 *   - Milestones (Revenue / EBITDA / EBIT / Net profit) render as full bars
 *     anchored to 0, width = milestone value as % of revenue.
 *   - Deductions (Materials / Services / Personnel / OpEx / D&A / Fin /
 *     Tax) render as FLOATING bars: each sits at the running balance,
 *     reflecting exactly what was subtracted between two milestones.
 *
 * Year picker + softer palette; expanded by default (per operator).
 *
 * Belgian GAAP rubrics (match backend whitelist in companies/financials.py):
 *   70    Revenue
 *   60    Materials
 *   61    Services
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
  value: number;          // absolute magnitude for display
  startPct: number;       // bar left edge (0..100)
  endPct: number;         // bar right edge (0..100)
  kind: "milestone" | "deduction";
  color: string;          // bar tailwind bg
  textColor: string;      // label text tailwind
  pctLabel?: string;      // inline % for milestones
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

  const revenue = rub(rubrics, "70", fy);
  if (revenue <= 0) return null;

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

  // Convert a raw EUR value to a % of revenue (0..100)
  const toPct = (v: number) => (v / revenue) * 100;

  // Palette: shades of gray only. Milestones get progressively darker as
  // the journey from top line to bottom line progresses; deductions stay
  // lightest. Negative bottom-line gets a muted gray too, with red
  // reserved for text when net is negative (so the chart stays quiet).
  const COL = {
    revenue:    "bg-slate-300",
    revenueTxt: "text-slate-700",
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

  const rows: Row[] = [];
  // Revenue — anchored to 0, soft sky colour (starting point).
  rows.push({
    label: "Revenue", value: revenue, kind: "milestone",
    startPct: 0, endPct: 100,
    color: COL.revenue, textColor: COL.revenueTxt,
    pctLabel: "100.0%",
  });

  // Deductions from revenue, running balance works downwards.
  let running = revenue;
  const pushDed = (label: string, v: number) => {
    if (v <= 0) return;
    const endPct = toPct(running);
    running -= v;
    const startPct = toPct(running);
    rows.push({
      label, value: v, kind: "deduction",
      startPct, endPct,
      color: COL.deduction, textColor: COL.deductionTxt,
    });
  };
  pushDed("− Materials",  materials);
  pushDed("− Services",   services);
  pushDed("− Personnel",  personnel);
  pushDed("− Other OpEx", otherOp);

  // EBITDA milestone — soft teal accent
  rows.push({
    label: "EBITDA", value: Math.max(0, ebitda), kind: "milestone",
    startPct: 0, endPct: Math.min(100, toPct(Math.max(0, ebitda))),
    color: COL.milestone, textColor: COL.milestoneTxt,
    pctLabel: revenue > 0 ? `${(ebitda / revenue * 100).toFixed(1)}%` : undefined,
  });

  // − D&A: floats between EBIT and EBITDA
  if (da > 0) {
    const endPct = toPct(Math.max(0, ebitda));
    const startPct = toPct(Math.max(0, ebit));
    rows.push({
      label: "− D&A", value: da, kind: "deduction",
      startPct: Math.min(startPct, endPct),
      endPct: Math.max(startPct, endPct),
      color: COL.deduction, textColor: COL.deductionTxt,
    });
  }

  // EBIT milestone — slightly stronger teal to mark journey progress
  rows.push({
    label: "EBIT", value: Math.max(0, ebit), kind: "milestone",
    startPct: 0, endPct: Math.min(100, Math.max(0, toPct(ebit))),
    color: COL.milestoneStrong, textColor: COL.milestoneStrongTxt,
    pctLabel: revenue > 0 ? `${(ebit / revenue * 100).toFixed(1)}%` : undefined,
  });

  // Fin charges + Tax bring EBIT down to Net profit.
  let ebitRunning = ebit;
  const pushBelowEbit = (label: string, v: number) => {
    if (v <= 0) return;
    const endPct = toPct(Math.max(0, ebitRunning));
    ebitRunning -= v;
    const startPct = toPct(Math.max(0, ebitRunning));
    rows.push({
      label, value: v, kind: "deduction",
      startPct: Math.min(startPct, endPct),
      endPct: Math.max(startPct, endPct),
      color: COL.deduction, textColor: COL.deductionTxt,
    });
  };
  pushBelowEbit("− Fin. charges", finCharges);
  pushBelowEbit("− Tax",          tax);

  // Net profit — bottom line. Green if positive, dusty rose if negative.
  rows.push({
    label: "Net profit", value: Math.max(0, netProfit), kind: "milestone",
    startPct: 0, endPct: Math.min(100, Math.max(0, toPct(netProfit))),
    color: netProfit >= 0 ? COL.netPos : COL.netNeg,
    textColor: netProfit >= 0 ? COL.netPosTxt : COL.netNegTxt,
    pctLabel: revenue > 0 ? `${(netProfit / revenue * 100).toFixed(1)}%` : undefined,
  });

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
                  <div className={`w-[110px] md:w-[140px] shrink-0 text-right truncate ${
                    isMilestone ? `font-semibold ${r.textColor}` : r.textColor
                  }`}>
                    {r.label}
                  </div>
                  <div className="flex-1 relative h-5 md:h-6 bg-slate-50 rounded overflow-hidden">
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
                    {fmtEur(r.value)}
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
