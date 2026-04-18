"use client";

import React, { useMemo, useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import { fmtEur } from "@/lib/format";

/* Horizontal waterfall: Revenue → Materials → Services → Personnel → Other
 * OpEx → EBITDA → D&A → EBIT → Fin charges → Tax → Net profit. Year picker
 * + collapsed by default + softer palette. Pure SVG/CSS, no dep.
 *
 * Belgian GAAP rubric mapping:
 *   70           Revenue
 *   60           Materials & consumables
 *   61           Services & other goods
 *   62           Personnel
 *   640          Other operating costs (residual bucket)
 *   630          Depreciation & amortisation
 *   9901         Operating profit (EBIT)
 *   65           Financial charges
 *   67           Tax
 *   9904         Net profit
 */

interface Props {
  rubrics: Record<string, Record<string, number | null>>;
  fiscalYears: number[];             // available years, newest first
  defaultCollapsed?: boolean;
}

function rub(r: Record<string, Record<string, number | null>>, code: string, fy: number): number {
  const v = r?.[code]?.[String(fy)];
  return typeof v === "number" ? v : 0;
}

type Row =
  | { label: string; value: number; kind: "milestone"; color: string; bar: string; pct?: number }
  | { label: string; value: number; kind: "deduction"; color: string; bar: string };

export function PnlWaterfall({ rubrics, fiscalYears, defaultCollapsed = true }: Props) {
  const years = useMemo(
    () => [...new Set(fiscalYears)].filter((y) => typeof y === "number").sort((a, b) => b - a),
    [fiscalYears],
  );

  const [open, setOpen] = useState(!defaultCollapsed);
  const [fy, setFy] = useState<number | null>(years[0] ?? null);

  if (!years.length || fy == null) return null;

  const revenue = rub(rubrics, "70", fy);
  if (revenue <= 0) return null;

  const materials = Math.max(0, rub(rubrics, "60", fy));
  const services = Math.max(0, rub(rubrics, "61", fy));
  const personnel = Math.max(0, rub(rubrics, "62", fy));
  const otherOp = Math.max(0, rub(rubrics, "640", fy));
  const da = Math.max(0, rub(rubrics, "630", fy));
  const ebit = rub(rubrics, "9901", fy);
  const ebitda = ebit + da;
  const finCharges = Math.max(0, rub(rubrics, "65", fy));
  const tax = Math.max(0, rub(rubrics, "67", fy));
  const netProfit = rub(rubrics, "9904", fy);

  // Softer, pastel-ish palette (text + bar variants)
  const rows: Row[] = [
    { label: "Revenue",            value: revenue,     kind: "milestone", color: "text-indigo-700", bar: "bg-indigo-300" },
  ];
  if (materials > 0) rows.push({ label: "− Materials",     value: materials, kind: "deduction", color: "text-rose-600", bar: "bg-rose-200" });
  if (services > 0)  rows.push({ label: "− Services",      value: services,  kind: "deduction", color: "text-rose-600", bar: "bg-rose-200" });
  if (personnel > 0) rows.push({ label: "− Personnel",     value: personnel, kind: "deduction", color: "text-rose-600", bar: "bg-rose-200" });
  if (otherOp > 0)   rows.push({ label: "− Other OpEx",    value: otherOp,   kind: "deduction", color: "text-rose-600", bar: "bg-rose-200" });

  rows.push({
    label: "EBITDA", value: Math.max(0, ebitda), kind: "milestone",
    color: "text-emerald-700", bar: "bg-emerald-300",
    pct: revenue > 0 ? (ebitda / revenue) * 100 : undefined,
  });
  if (da > 0) rows.push({ label: "− D&A", value: da, kind: "deduction", color: "text-amber-600", bar: "bg-amber-200" });
  rows.push({
    label: "EBIT", value: Math.max(0, ebit), kind: "milestone",
    color: "text-emerald-700", bar: "bg-emerald-300",
    pct: revenue > 0 ? (ebit / revenue) * 100 : undefined,
  });
  if (finCharges > 0) rows.push({ label: "− Fin. charges", value: finCharges, kind: "deduction", color: "text-rose-600", bar: "bg-rose-200" });
  if (tax > 0)        rows.push({ label: "− Tax",          value: tax,        kind: "deduction", color: "text-slate-500", bar: "bg-slate-200" });
  rows.push({
    label: "Net profit", value: Math.max(0, netProfit), kind: "milestone",
    color: netProfit >= 0 ? "text-emerald-800" : "text-rose-700",
    bar: netProfit >= 0 ? "bg-emerald-400" : "bg-rose-300",
    pct: revenue > 0 ? (netProfit / revenue) * 100 : undefined,
  });

  const maxBar = revenue;

  return (
    <div className="rounded-lg border bg-white">
      {/* Header — click to toggle */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          {open ? <ChevronDown className="h-3.5 w-3.5 text-slate-400" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-400" />}
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
            P&amp;L waterfall
          </h3>
          <span className="text-[10px] text-slate-400">— FY{fy}</span>
        </div>
        {/* Year picker — clickable without toggling collapse */}
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
                  <div className={`w-[110px] md:w-[140px] shrink-0 text-right truncate ${
                    isMilestone ? `font-semibold ${r.color}` : "text-slate-500"
                  }`}>
                    {r.label}
                  </div>
                  <div className="flex-1 relative h-5 md:h-6 bg-slate-50 rounded overflow-hidden">
                    <div
                      className={`absolute left-0 top-0 h-full rounded ${r.bar}`}
                      style={{ width: `${pct}%` }}
                    />
                    {isMilestone && "pct" in r && r.pct != null && (
                      <span className="absolute right-1.5 top-0 h-full flex items-center text-[10px] text-slate-700 font-mono font-semibold">
                        {r.pct.toFixed(1)}%
                      </span>
                    )}
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
            Bars scaled to Revenue (100%). Milestones show margin % vs revenue.
          </p>
        </div>
      )}
    </div>
  );
}
